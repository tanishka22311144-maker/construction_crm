"""Stage 2 Meta (WhatsApp Cloud API) webhook handler.

Handles webhook verification and executes the Stage 2 LangGraph StateGraph
with read-only tool execution and session-variable RLS.
"""
import hashlib
import json
import os
import uuid
from urllib import request as urlrequest

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, PlainTextResponse

from agent.graph import graph

app = FastAPI()
handler = app  # Vercel entrypoint alias


from fastapi import APIRouter
import socket

debug_router = APIRouter()

@debug_router.get("/tcp-test")
async def tcp_test():
    """Try a plain TCP connection to the Supabase host."""
    host = "db.wajzaygkvprhpwxewdte.supabase.co"
    port = 5432
    try:
        with socket.create_connection((host, port), timeout=3):
            return {"status": "ok", "detail": f"Connected to {host}:{port}"}
    except Exception as exc:
        return {"status": "error", "detail": str(exc)}

app.include_router(debug_router)

@app.get("/api/index")
async def verify_webhook(request: Request):
    """Meta's GET verification handshake: echo hub.challenge when
    hub.verify_token matches."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    verify_token = os.getenv("META_VERIFY_TOKEN", "")
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

    # Compute sender hash (SHA-256) for identity anchor
    sender_hash = ""
    if sender_wa_id:
        sender_hash = hashlib.sha256(str(sender_wa_id).strip().encode("utf-8")).hexdigest()

    thread_id = f"wa-{sender_hash[:16]}" if sender_hash else f"thread-{uuid.uuid4().hex[:12]}"

    initial_state = {
        "incoming_message": incoming_text,
        "message_id": message_id,
        "sender_wa_id": sender_wa_id,
        "sender_hash": sender_hash,
        "thread_id": thread_id,
    }

    result = graph.invoke(
        initial_state,
        config={"configurable": {"thread_id": thread_id}},
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
    token = os.getenv("META_WHATSAPP_TOKEN", "")
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID", "")
    if not token or not phone_number_id or not to_wa_id:
        print(json.dumps({
            "event": "send_whatsapp_reply_skipped",
            "reason": "missing token/phone_number_id/recipient",
        }))
        return

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_wa_id,
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
@app.get("/health-db")
async def health_db():
    try:
        from project.services.database import get_db_connection
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT 1;")
                cur.fetchone()
        return {"status": "ok"}
    except Exception as e:
        return {"status": "error", "detail": str(e)}

from fastapi import APIRouter

debug_router = APIRouter()

@debug_router.get("/test-db")
async def test_db():
    """Attempt a DB connection and return diagnostics."""
    import traceback
    try:
        from project.services.database import get_db_connection
        with get_db_connection() as conn:
            with conn.cursor() as cur:
                cur.execute("SELECT version();")
                row = cur.fetchone()
        return {"status": "ok", "postgres_version": row}
    except Exception as exc:
        return {"status": "error", "detail": str(exc), "traceback": traceback.format_exc()}

app.include_router(debug_router)
