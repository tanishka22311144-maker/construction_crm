"""Stage 2 Meta (WhatsApp Cloud API) webhook handler.

Handles webhook verification and executes the Stage 2 LangGraph StateGraph
with read-only tool execution and session-variable RLS.
"""
import json
import os
import uuid
from urllib import request as urlrequest

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from api.dashboard_ui import get_dashboard_html

from agent.graph import graph
from services.audit import check_and_start_message_dedup, complete_message_dedup
from services.identity import canonicalize_whatsapp_number, hash_whatsapp_number

app = FastAPI()
handler = app  # Vercel entrypoint alias


@app.get("/api/index")
async def verify_webhook(request: Request):
    """Meta's GET verification handshake: echo hub.challenge when
    hub.verify_token matches."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    verify_token = os.getenv("META_VERIFY_TOKEN") or os.getenv("VERIFY_TOKEN", "")
    if mode == "subscribe" and token and verify_token and token == verify_token:
        return PlainTextResponse(challenge or "")
    return PlainTextResponse("Verification failed", status_code=403)


@app.post("/api/index")
async def receive_webhook(request: Request):
    """POST handler: extract message, invoke LangGraph state graph,
    and return WhatsApp response."""
    try:
        body = await request.json()
    except json.JSONDecodeError:
        return JSONResponse({"error": "invalid payload"}, status_code=400)

    incoming_text, sender_wa_id, message_id = _extract_message(body)
    if incoming_text is None:
        return JSONResponse({"status": "ignored"})

    # Canonicalize sender number and compute SHA-256 identity hash
    canonical_sender = canonicalize_whatsapp_number(sender_wa_id) if sender_wa_id else ""
    sender_hash = hash_whatsapp_number(sender_wa_id) if sender_wa_id else ""

    # Stage 4 Deduplication Check (PROJECT_SPEC.md §10 & idempotency skill)
    if message_id:
        dedup_result = check_and_start_message_dedup(message_id, sender_hash)
        if dedup_result.get("is_duplicate"):
            print(json.dumps({
                "event": "message_deduplicated",
                "message_id": message_id,
                "dedup_status": dedup_result.get("status"),
            }), flush=True)
            return JSONResponse({
                "status": "already_processed",
                "message_id": message_id,
            })

    # Safe diagnostic logging of sender hash and env status (no secrets or raw phone)
    print(json.dumps({
        "event": "webhook_received",
        "sender_hash": sender_hash,
        "env_check": {
            "has_meta_token": bool(os.getenv("META_WHATSAPP_TOKEN") or os.getenv("META_ACCESS_TOKEN")),
            "has_phone_number_id": bool(os.getenv("META_PHONE_NUMBER_ID")),
        },
    }), flush=True)

    # Check if this incoming message is an approval reply (e.g. APPROVE APR-XXXX, REJECT APR-XXXX <reason>, EDIT APR-XXXX <changes>, or shorthand "approve" / "reject")
    from services.approvals import parse_approval_reply, validate_and_process_approval, find_latest_pending_approval_code
    approval_reply = parse_approval_reply(incoming_text)
    if approval_reply:
        approval_code = approval_reply["approval_code"]
        action = approval_reply["action"]
        extra_text = approval_reply["extra_text"]

        # If approval_code was omitted (e.g. user typed just "approve"), infer it from recent AI reply or pending_approvals
        if not approval_code:
            approval_code = find_latest_pending_approval_code(sender_hash=sender_hash)

        if not approval_code:
            err_msg = f"No pending approval request found to {action.lower()}. Please include the approval code (e.g. APPROVE APR-XXXX)."
            if sender_wa_id:
                _send_whatsapp_reply(sender_wa_id, err_msg)
            if message_id:
                complete_message_dedup(message_id, run_id="appr-not-found")
            return JSONResponse({
                "status": "approval_rejected",
                "reason": "no_pending_approval",
                "details": f"Could not find any pending approval to {action.lower()}",
            })

        # Run 5-point deterministic verification checklist
        approval_res = validate_and_process_approval(
            approval_code=approval_code,
            approver_sender_hash=sender_hash,
            action=action,
            extra_text=extra_text,
        )

        if not approval_res.get("valid"):
            reason = approval_res.get("decision_reason", "invalid_approval_context")
            details = approval_res.get("details", "")
            err_msg = f"Approval {approval_code} {action.lower()} rejected: {reason}."
            if sender_wa_id:
                _send_whatsapp_reply(sender_wa_id, err_msg)
            if message_id:
                complete_message_dedup(message_id, run_id=f"appr-{approval_code}")
            return JSONResponse({
                "status": "approval_rejected",
                "reason": reason,
                "details": details,
            })

        # All 5 verification checks passed!
        target_thread_id = approval_res.get("thread_id")
        decision_val = approval_res.get("decision")
        decision_reason = approval_res.get("decision_reason")
        edited_payload = approval_res.get("edited_payload")

        # Resume the paused thread using thread_id
        resumed_result = None
        if target_thread_id:
            try:
                from langgraph.types import Command
                resume_cmd = Command(resume={
                    "decision": decision_val,
                    "decision_reason": decision_reason,
                    "edited_payload": edited_payload,
                })
                resumed_result = graph.invoke(
                    resume_cmd,
                    config={"configurable": {"thread_id": target_thread_id}},
                )
            except Exception as resume_err:
                print(json.dumps({"event": "resume_graph_error", "error": str(resume_err)}), flush=True)

        final_msg = ""
        requester_wa_id = None
        if resumed_result and isinstance(resumed_result, dict):
            final_msg = resumed_result.get("final_response", "")
            requester_wa_id = resumed_result.get("sender_wa_id")

        if not final_msg:
            if action == "APPROVE":
                final_msg = f"Approval {approval_code} confirmed and completed successfully."
            elif action == "REJECT":
                final_msg = f"Request {approval_code} was rejected: {decision_reason}"
            else:
                final_msg = f"Request {approval_code} was edited and updated."

        # Verify criteria: Confirm original requester gets confirmation
        if requester_wa_id and requester_wa_id != canonical_sender:
            _send_whatsapp_reply(requester_wa_id, final_msg)

        # Notify the approver who sent the approval reply
        approver_ack = f"Approval {approval_code} processed: {action.lower()}."
        if sender_wa_id:
            _send_whatsapp_reply(sender_wa_id, approver_ack)

        if message_id:
            complete_message_dedup(message_id, run_id=f"appr-{approval_code}")

        return JSONResponse({
            "status": "ok",
            "approval_code": approval_code,
            "decision": decision_val,
            "final_response": final_msg,
        })

    # Standard user request flow
    thread_id = f"wa-{sender_hash[:16]}" if sender_hash else f"thread-{uuid.uuid4().hex[:12]}"
    run_id = f"run-{uuid.uuid4().hex[:12]}"
    initial_state = {
        "run_id": run_id,
        "incoming_message": incoming_text,
        "message_id": message_id,
        "sender_wa_id": canonical_sender,
        "sender_hash": sender_hash,
        "thread_id": thread_id,
    }

    langgraph_config = {
        "configurable": {"thread_id": thread_id},
        "metadata": {
            "run_id": run_id,
            "user_hash": sender_hash,
            "environment": os.getenv("VERCEL_ENV", "production"),
        },
    }

    result = graph.invoke(
        initial_state,
        config=langgraph_config,
    )
    final_response = result.get("final_response", "")

    # Mark message deduplication as complete
    if message_id:
        complete_message_dedup(message_id, run_id=run_id)

    if sender_wa_id and final_response:
        _send_whatsapp_reply(sender_wa_id, final_response)

    return JSONResponse({
        "status": "ok",
        "final_response": final_response,
        "goal_complete": result.get("goal_complete", False),
        "approval_id": result.get("approval_id"),
        "approval_code": result.get("approval_code"),
    })


def _extract_message(body: dict):
    try:
        entry = body["entry"][0]
        change = entry["changes"][0]["value"]
        message = change["messages"][0]
        text = message.get("text", {}).get("body")
        sender_wa_id = message.get("from")
        message_id = message.get("id")
        return text, sender_wa_id, message_id
    except (KeyError, IndexError, TypeError):
        return None, None, None


def _send_whatsapp_reply(to_wa_id: str, text: str) -> None:
    canonical_recipient = canonicalize_whatsapp_number(to_wa_id) if to_wa_id else ""
    token = os.getenv("META_WHATSAPP_TOKEN") or os.getenv("META_ACCESS_TOKEN") or ""
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "")

    has_token = bool(token)
    has_phone_id = bool(phone_number_id)
    has_recipient = bool(canonical_recipient)

    if not (has_token and has_phone_id and has_recipient):
        print(json.dumps({
            "event": "send_whatsapp_reply_skipped",
            "reason": "missing token/phone_number_id/recipient",
            "env_check": {
                "has_token": has_token,
                "has_phone_number_id": has_phone_id,
                "has_recipient": has_recipient,
            },
        }), flush=True)
        return

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": canonical_recipient,
        "type": "text",
        "text": {"body": text},
    }
    req = urlrequest.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urlrequest.urlopen(req, timeout=15) as response:
            print(json.dumps({"event": "send_whatsapp_reply_ok", "status": response.status}))
    except Exception as exc:  # pragma: no cover - runtime safeguard
        err_detail = str(exc)
        if hasattr(exc, "read"):
            try:
                err_detail = f"{str(exc)}: {exc.read().decode('utf-8', errors='replace')}"
            except Exception:
                pass
        print(json.dumps({"event": "send_whatsapp_reply_failed", "error": err_detail}))


# -------------------------------------------------------------
# Stage 7 — Web Dashboard & Real-Time Project Excel Endpoints
# -------------------------------------------------------------

@app.get("/")
@app.get("/dashboard")
async def get_dashboard():
    """Serve the Stage 7 web dashboard with prediction graphs and real-time Excel engine."""
    supabase_url = os.getenv("SUPABASE_URL", "https://wajzaygkvprhpwxewdte.supabase.co")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndhanpheWdrdnByaHB3eGV3ZHRlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU2NjkzNjYsImV4cCI6MjEwMTI0NTM2Nn0.yrOagbQ_rhC7GKAkz4fe92CHXmNCjp1KvHXFroUTXuU")
    html_content = get_dashboard_html(supabase_url=supabase_url, supabase_anon_key=supabase_anon_key)
    return HTMLResponse(content=html_content)


@app.get("/api/projects")
async def list_projects():
    """List all projects for the dashboard project selector."""
    try:
        from services.database import execute_query
        rows = execute_query(
            "SELECT id, project_name, project_code, location, status, created_at FROM public.projects ORDER BY created_at DESC"
        )
        for r in rows:
            if r.get("id"):
                r["id"] = str(r["id"])
            if r.get("created_at") and hasattr(r["created_at"], "isoformat"):
                r["created_at"] = r["created_at"].isoformat()
        return {"projects": rows}
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/projects/{project_id}/prediction")
async def get_prediction(project_id: str):
    """Return S-curve planned schedule, actual cumulative work, and velocity forecast."""
    try:
        from services.prediction import calculate_project_prediction
        pred = calculate_project_prediction(project_id)
        return pred
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/projects/{project_id}/spreadsheet")
async def get_spreadsheet(project_id: str):
    """Return tabular data and column metadata for the project's dedicated in-browser Excel editor."""
    try:
        from services.excel_service import get_project_spreadsheet_data
        data = get_project_spreadsheet_data(project_id)
        return data
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.get("/api/projects/{project_id}/excel")
async def download_excel(project_id: str):
    """Generate and stream a styled .xlsx binary workbook for this project."""
    try:
        from services.excel_service import generate_project_excel, get_project_spreadsheet_data
        meta = get_project_spreadsheet_data(project_id)
        proj_code = meta["project"]["project_code"] or "project"
        excel_bytes = generate_project_excel(project_id)
        filename = f"{proj_code}_records.xlsx"
        return Response(
            content=excel_bytes,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/projects/{project_id}/sync_row")
async def sync_row(project_id: str, request: Request):
    """Real-time sync endpoint: receives Excel row edit/insert and writes to Supabase."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)

    try:
        from services.excel_service import sync_excel_row_to_supabase
        result = sync_excel_row_to_supabase(project_id, body)
        status_code = 200 if result.get("success") else 400
        return JSONResponse(result, status_code=status_code)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# --- Debug / health endpoints (non-production) ---

@app.get("/health-db")
async def health_db():
    """Quick Postgres connectivity check."""
    try:
        from services.database import get_db_connection
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}
