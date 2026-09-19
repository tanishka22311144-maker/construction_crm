"""Stage 2 Meta (WhatsApp Cloud API) webhook handler.

Handles webhook verification and executes the Stage 2 LangGraph StateGraph
with read-only tool execution and session-variable RLS.
"""
import json
import os
import uuid
from urllib import request as urlrequest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agent.graph import graph
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

    # Safe diagnostic logging of sender hash and env status (no secrets or raw phone)
    print(json.dumps({
        "event": "webhook_received",
        "sender_hash": sender_hash,
        "env_check": {
            "has_meta_token": bool(os.getenv("META_WHATSAPP_TOKEN") or os.getenv("META_ACCESS_TOKEN")),
            "has_phone_number_id": bool(os.getenv("META_PHONE_NUMBER_ID")),
        },
    }), flush=True)

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

    if sender_wa_id:
        _send_whatsapp_reply(sender_wa_id, final_response)

    return JSONResponse({
        "status": "ok",
        "final_response": final_response,
        "goal_complete": result.get("goal_complete", False),
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
        print(json.dumps({"event": "send_whatsapp_reply_failed", "error": str(exc)}))


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
