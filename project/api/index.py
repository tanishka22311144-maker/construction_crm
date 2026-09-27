"""Stage 2 Meta (WhatsApp Cloud API) webhook handler.

Handles webhook verification and executes the Stage 2 LangGraph StateGraph
with read-only tool execution and session-variable RLS.
"""
from datetime import datetime, date, timezone
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
    if mode == "subscribe":
        if token and verify_token and token == verify_token:
            return PlainTextResponse(challenge or "")
        return PlainTextResponse("Verification failed", status_code=403)
    # If opened in a browser directly without hub.mode, serve the dashboard
    return await get_dashboard()


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
@app.get("/api/dashboard")
@app.get("/api/index/dashboard")
async def get_dashboard():
    """Serve the Stage 7 web dashboard with prediction graphs and real-time Excel engine."""
    supabase_url = os.getenv("SUPABASE_URL", "https://wajzaygkvprhpwxewdte.supabase.co")
    supabase_anon_key = os.getenv("SUPABASE_ANON_KEY", "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJpc3MiOiJzdXBhYmFzZSIsInJlZiI6IndhanpheWdrdnByaHB3eGV3ZHRlIiwicm9sZSI6ImFub24iLCJpYXQiOjE3ODU2NjkzNjYsImV4cCI6MjEwMTI0NTM2Nn0.yrOagbQ_rhC7GKAkz4fe92CHXmNCjp1KvHXFroUTXuU")
    html_content = get_dashboard_html(supabase_url=supabase_url, supabase_anon_key=supabase_anon_key)
    return HTMLResponse(content=html_content)


@app.get("/api/projects")
@app.get("/api/index/projects")
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
@app.get("/api/index/projects/{project_id}/prediction")
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
@app.get("/api/index/projects/{project_id}/spreadsheet")
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
@app.get("/api/index/projects/{project_id}/excel")
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
            headers={
                "Content-Disposition": f'attachment; filename="{filename}"',
                "Access-Control-Expose-Headers": "Content-Disposition",
            },
        )
    except ValueError as e:
        return JSONResponse({"error": str(e)}, status_code=404)
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


@app.post("/api/projects/{project_id}/sync_row")
@app.post("/api/index/projects/{project_id}/sync_row")
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


@app.post("/api/projects/create")
@app.post("/api/index/projects/create")
async def create_project_route(request: Request):
    """Create a new project from dashboard."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)

    try:
        from services.excel_service import create_new_project
        result = create_new_project(
            project_name=body.get("project_name", ""),
            project_code=body.get("project_code"),
            location=body.get("location"),
            status=body.get("status", "active"),
        )
        return JSONResponse(result, status_code=201)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.delete("/api/projects/{project_id}")
@app.delete("/api/index/projects/{project_id}")
@app.post("/api/projects/{project_id}/delete")
@app.post("/api/index/projects/{project_id}/delete")
async def delete_project_route(project_id: str):
    """Delete a project and cascade-remove its records, field definitions, and access."""
    try:
        from services.excel_service import delete_project
        result = delete_project(project_id)
        if not result.get("success"):
            return JSONResponse(result, status_code=400)
        return JSONResponse(result, status_code=200)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/projects/{project_id}/import_excel")
@app.post("/api/index/projects/{project_id}/import_excel")
async def import_excel_route(project_id: str, request: Request):
    """Import and reconcile an Excel workbook into an existing project."""
    content_type = request.headers.get("content-type", "")
    file_bytes = b""
    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
            file_obj = form.get("file")
            if file_obj and hasattr(file_obj, "read"):
                file_bytes = await file_obj.read()
        except Exception:
            file_bytes = await request.body()
    else:
        file_bytes = await request.body()

    if not file_bytes:
        return JSONResponse({"success": False, "error": "No file content received"}, status_code=400)

    try:
        from services.excel_service import import_project_excel
        result = import_project_excel(file_bytes=file_bytes, project_id=project_id)
        return JSONResponse(result, status_code=200)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


@app.post("/api/projects/import_new")
@app.post("/api/index/projects/import_new")
async def import_new_project_route(request: Request):
    """Create a new project and import all sheets directly from an uploaded Excel workbook."""
    content_type = request.headers.get("content-type", "")
    file_bytes = b""
    project_name = request.query_params.get("project_name") or request.headers.get("X-Project-Name")
    project_code = request.query_params.get("project_code") or request.headers.get("X-Project-Code")
    location = request.query_params.get("location") or request.headers.get("X-Project-Location")

    if "multipart/form-data" in content_type:
        try:
            form = await request.form()
            file_obj = form.get("file")
            if file_obj and hasattr(file_obj, "read"):
                file_bytes = await file_obj.read()
            project_name = form.get("project_name") or project_name
            project_code = form.get("project_code") or project_code
            location = form.get("location") or location
        except Exception:
            file_bytes = await request.body()
    else:
        file_bytes = await request.body()

    if not file_bytes:
        return JSONResponse({"success": False, "error": "No file content received"}, status_code=400)

    try:
        from services.excel_service import import_project_excel
        result = import_project_excel(
            file_bytes=file_bytes,
            project_id=None,
            project_name=project_name,
            project_code=project_code,
            location=location,
        )
        return JSONResponse(result, status_code=201)
    except ValueError as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=400)
    except Exception as e:
        return JSONResponse({"success": False, "error": str(e)}, status_code=500)


# --- WhatsApp Authentication & Self-Registration Endpoints ---

@app.post("/api/auth/login")
@app.post("/api/index/auth/login")
async def auth_login(request: Request):
    """Log in using a WhatsApp phone number.
    If user is not yet in public.agent_users, auto-register as 'project_admin'.
    """
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)

    phone = str(body.get("phone_number") or "").strip()
    if not phone:
        return JSONResponse({"success": False, "error": "Phone number is required"}, status_code=400)

    from services.identity import canonicalize_whatsapp_number, hash_whatsapp_number
    from services.database import get_db_connection

    canonical = canonicalize_whatsapp_number(phone)
    if not canonical:
        return JSONResponse({"success": False, "error": "Invalid phone number format"}, status_code=400)

    sender_hash = hash_whatsapp_number(canonical)
    custom_name = str(body.get("display_name") or "").strip()

    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, display_name, role, is_active, created_at
                FROM public.agent_users
                WHERE whatsapp_sender_hash = %s
                LIMIT 1
                """,
                (sender_hash,),
            )
            user_row = cur.fetchone()

            if user_row:
                user = dict(user_row)
                if not user.get("is_active"):
                    return JSONResponse({"success": False, "error": "User account is inactive"}, status_code=403)
                if custom_name and custom_name != user.get("display_name"):
                    cur.execute(
                        "UPDATE public.agent_users SET display_name = %s WHERE id = %s",
                        (custom_name, user["id"]),
                    )
                    user["display_name"] = custom_name
            else:
                display_name = custom_name or f"+{canonical}"
                cur.execute(
                    """
                    INSERT INTO public.agent_users (whatsapp_sender_hash, display_name, role, is_active)
                    VALUES (%s, %s, 'project_admin', true)
                    RETURNING id, display_name, role, is_active, created_at
                    """,
                    (sender_hash, display_name),
                )
                user = dict(cur.fetchone())

    masked_phone = f"+{canonical[:2]} {canonical[2:5]}***{canonical[-2:]}" if len(canonical) >= 7 else f"+{canonical}"
    user["phone"] = f"+{canonical}"
    user["phone_masked"] = masked_phone
    user["sender_hash"] = sender_hash
    if isinstance(user.get("created_at"), (datetime, date)):
        user["created_at"] = user["created_at"].isoformat()
    user["id"] = str(user["id"])

    return JSONResponse({
        "success": True,
        "user": user,
        "message": f"Logged in as {user.get('display_name')} ({user.get('role')})",
    })


@app.get("/api/auth/me")
@app.get("/api/index/auth/me")
async def auth_me(request: Request):
    """Check current authenticated session."""
    sender_hash = request.query_params.get("sender_hash") or request.headers.get("X-Sender-Hash")
    if not sender_hash:
        return JSONResponse({"success": False, "error": "Not authenticated"}, status_code=401)

    from services.database import get_db_connection
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT id, display_name, role, is_active, created_at
                FROM public.agent_users
                WHERE whatsapp_sender_hash = %s AND is_active = true
                LIMIT 1
                """,
                (sender_hash,),
            )
            user_row = cur.fetchone()
            if not user_row:
                return JSONResponse({"success": False, "error": "User not found or inactive"}, status_code=404)
            user = dict(user_row)
            user["id"] = str(user["id"])
            if isinstance(user.get("created_at"), (datetime, date)):
                user["created_at"] = user["created_at"].isoformat()
            user["sender_hash"] = sender_hash
            return JSONResponse({"success": True, "user": user})


# --- Pending Approvals Management Endpoints ---

@app.get("/api/approvals/pending")
@app.get("/api/index/approvals/pending")
async def list_pending_approvals():
    """List all pending approvals for project and field creations."""
    from services.database import get_db_connection
    with get_db_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT pa.id, pa.run_id, pa.thread_id, pa.required_approver_role,
                       pa.operation, pa.proposed_payload, pa.status, pa.requested_at, pa.expires_at,
                       u.display_name as requester_name
                FROM public.pending_approvals pa
                LEFT JOIN public.agent_users u ON u.id = pa.requested_by
                WHERE pa.status = 'pending'
                ORDER BY pa.requested_at DESC
                """
            )
            rows = cur.fetchall()

    approvals = []
    for r in rows:
        item = dict(r)
        item["id"] = str(item["id"])
        item["requested_at"] = item["requested_at"].isoformat() if item.get("requested_at") else None
        item["expires_at"] = item["expires_at"].isoformat() if item.get("expires_at") else None
        
        payload = item.get("proposed_payload") or {}
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                payload = {}
        
        approval_code = payload.get("approval_code") or f"APR-{item['id'][:6].upper()}"
        item["approval_code"] = approval_code
        item["project_name"] = payload.get("project_name") or payload.get("name") or "General"
        item["project_code"] = payload.get("project_code")
        item["field_name"] = payload.get("field_name")
        item["field_type"] = payload.get("field_type")
        item["record_type"] = payload.get("record_type")
        item["proposed_payload"] = payload
        approvals.append(item)

    return JSONResponse({"success": True, "approvals": approvals, "count": len(approvals)})


@app.post("/api/approvals/{approval_id}/decision")
@app.post("/api/index/approvals/{approval_id}/decision")
async def decide_approval_route(approval_id: str, request: Request):
    """Approve or reject a pending approval directly from the dashboard."""
    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"success": False, "error": "Invalid JSON body"}, status_code=400)

    decision = str(body.get("decision") or "").strip().upper()
    if decision not in ("APPROVE", "REJECT"):
        return JSONResponse({"success": False, "error": "Decision must be APPROVE or REJECT"}, status_code=400)

    sender_hash = body.get("sender_hash") or request.headers.get("X-Sender-Hash")
    if not sender_hash:
        return JSONResponse({"success": False, "error": "Authentication required to approve"}, status_code=401)

    reason = str(body.get("reason") or ("Approved via Dashboard" if decision == "APPROVE" else "Rejected via Dashboard")).strip()

    from services.database import get_db_connection
    from services.excel_service import create_new_project

    with get_db_connection(sender_hash=sender_hash) as conn:
        with conn.cursor() as cur:
            # 1. Verify approver has permissions
            cur.execute(
                "SELECT id, display_name, role FROM public.agent_users WHERE whatsapp_sender_hash = %s AND is_active = true",
                (sender_hash,),
            )
            approver = cur.fetchone()
            if not approver:
                return JSONResponse({"success": False, "error": "Approver not found or inactive"}, status_code=403)
            
            approver_role = approver["role"]
            if approver_role not in ("project_admin", "system_admin"):
                return JSONResponse({"success": False, "error": "Only admins can approve requests"}, status_code=403)

            from services.database import bind_request_context
            bind_request_context(conn, sender_hash=sender_hash, user_id=str(approver["id"]))

            # 2. Lookup pending approval
            clean_id = approval_id.strip()
            cur.execute(
                """
                SELECT id, run_id, thread_id, requested_by, required_approver_role,
                       operation, proposed_payload, status, expires_at
                FROM public.pending_approvals
                WHERE id = %s OR id::text LIKE %s
                LIMIT 1
                """,
                (clean_id if len(clean_id) == 36 else None, f"{clean_id}%"),
            )
            appr = cur.fetchone()
            if not appr:
                return JSONResponse({"success": False, "error": "Approval request not found"}, status_code=404)
            
            if appr["status"] != "pending":
                return JSONResponse({"success": False, "error": f"Approval is already {appr['status']}"}, status_code=400)

            appr_id = appr["id"]
            operation = appr["operation"]
            payload = appr["proposed_payload"] or {}
            if isinstance(payload, str):
                try:
                    payload = json.loads(payload)
                except Exception:
                    payload = {}

            now = datetime.now(timezone.utc)
            new_status = "approved" if decision == "APPROVE" else "rejected"

            # 3. Update pending_approvals record with read-back verification
            cur.execute(
                """
                UPDATE public.pending_approvals
                SET status = %s,
                    decision = %s,
                    decision_reason = %s,
                    decided_by = %s,
                    decided_at = %s
                WHERE id = %s
                RETURNING id, status, decision
                """,
                (new_status, decision.lower(), reason, approver["id"], now, appr_id),
            )
            updated_appr = cur.fetchone()
            if not updated_appr:
                return JSONResponse({"success": False, "error": f"Failed to update approval {clean_id} in database."}, status_code=500)

            # 4. If approved, execute the corresponding operation!
            execution_details = None
            if decision == "APPROVE":
                if operation == "create_project":
                    p_name = payload.get("project_name")
                    p_code = payload.get("project_code")
                    p_loc = payload.get("location")
                    p_status = payload.get("status") or "active"

                    # Check if project already exists to avoid duplicate projects
                    cur.execute(
                        "SELECT id, project_name, project_code FROM public.projects WHERE lower(project_name) = lower(%s) OR (project_code IS NOT NULL AND lower(project_code) = lower(%s)) LIMIT 1",
                        (p_name, p_code or ""),
                    )
                    existing_proj = cur.fetchone()
                    if existing_proj:
                        res = {"success": True, "project": dict(existing_proj), "message": "Project already exists"}
                    else:
                        res = create_new_project(
                            project_name=p_name,
                            project_code=p_code,
                            location=p_loc,
                            status=p_status,
                            auto_disambiguate_code=True,
                        )
                    execution_details = res
                    target_proj_id = res.get("project", {}).get("id") or (existing_proj["id"] if existing_proj else None)
                    if appr.get("requested_by") and target_proj_id:
                        try:
                            cur.execute(
                                """
                                INSERT INTO public.user_project_access (user_id, project_id, role)
                                VALUES (%s, %s, 'project_admin')
                                ON CONFLICT (user_id, project_id) DO NOTHING
                                """,
                                (appr["requested_by"], target_proj_id),
                            )
                        except Exception:
                            pass

                elif operation == "create_project_field":
                    proj_id = payload.get("project_id")
                    if not proj_id and payload.get("project_name"):
                        cur.execute("SELECT id FROM public.projects WHERE lower(project_name) = lower(%s) LIMIT 1", (payload["project_name"],))
                        p_row = cur.fetchone()
                        if p_row:
                            proj_id = p_row["id"]
                    
                    if proj_id:
                        f_name = payload.get("field_name")
                        f_type = payload.get("field_type") or "text"
                        r_type = payload.get("record_type") or "daily_work_done"
                        req = bool(payload.get("required", False))
                        cur.execute(
                            """
                            INSERT INTO public.project_field_definitions
                                (project_id, record_type, field_name, field_type, required)
                            VALUES (%s, %s, %s, %s, %s)
                            ON CONFLICT (project_id, record_type, field_name) DO UPDATE
                            SET field_type = EXCLUDED.field_type
                            RETURNING id, project_id, record_type, field_name, field_type
                            """,
                            (proj_id, r_type, f_name, f_type, req),
                        )
                        execution_details = {"field": dict(cur.fetchone() or {})}

                elif operation in ("add_project_row", "write"):
                    from tools.add_project_row import add_project_row
                    res = add_project_row(
                        project_id=payload.get("project_id"),
                        record_type=payload.get("record_type") or "expense",
                        record_date=payload.get("record_date"),
                        title=payload.get("title") or payload.get("expense_title") or "Expense",
                        description=payload.get("description"),
                        amount=payload.get("amount"),
                        unit=payload.get("unit") or "INR",
                        data=payload.get("data") or {},
                        user_id=str(approver["id"]),
                        sender_hash=sender_hash,
                    )
                    execution_details = res

    # 5. Optionally resume thread if thread_id exists
    thread_id = appr.get("thread_id")
    if thread_id:
        try:
            from langgraph.types import Command
            resume_cmd = Command(resume={
                "decision": decision.lower(),
                "decision_reason": reason,
                "edited_payload": payload,
            })
            graph.invoke(
                resume_cmd,
                config={"configurable": {"thread_id": thread_id}},
            )
        except Exception as e:
            print(f"[Approval Web Resume Warning] {e}", flush=True)

    approval_code = payload.get("approval_code") or f"APR-{str(appr_id)[:6].upper()}"
    return JSONResponse({
        "success": True,
        "approval_id": str(appr_id),
        "approval_code": approval_code,
        "decision": decision,
        "message": f"Approval {approval_code} {decision.lower()}d successfully.",
        "execution": execution_details,
    })



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
