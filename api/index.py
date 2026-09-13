"""Stage 1 webhook entry point.

GET: Meta verification handshake.
POST: Extract the first WhatsApp message and run the agent pipeline.
"""

import hashlib
import json
import os
import sys
import urllib.parse
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import urllib.request
from agent.graph import run_agent

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "dev-verify-token")


def log_step(step: str, **details):
    if os.getenv("DEBUG_LOGS", "1").lower() in {"0", "false", "no", "off"}:
        return
    payload = {"event": "webhook_trace", "step": step}
    for key, value in details.items():
        if isinstance(value, str) and ("token" in key.lower() or "secret" in key.lower() or "key" in key.lower()):
            payload[key] = "***redacted***"
        elif isinstance(value, str) and len(value) > 200:
            payload[key] = value[:200] + "..."
        else:
            payload[key] = value
    print(json.dumps(payload, default=str), flush=True)


def json_response(start_response, obj, status="200 OK"):
    body = json.dumps(obj).encode("utf-8")
    headers = [("Content-Type", "application/json"), ("Content-Length", str(len(body)))]
    start_response(status, headers)
    return [body]


def hash_sender(sender: str) -> str:
    return hashlib.sha256(sender.encode("utf-8")).hexdigest()


def send_whatsapp_message(to_number: str, body: str):
    access_token = os.environ.get("META_ACCESS_TOKEN")
    phone_number_id = os.environ.get("META_PHONE_NUMBER_ID")
    log_step(
        "meta_send_start",
        to_number=to_number,
        body_preview=body[:180],
        access_token_present=bool(access_token),
        phone_number_id_present=bool(phone_number_id),
    )
    if not access_token or not phone_number_id:
        log_step("meta_send_missing_credentials")
        return {"sent": False, "reason": "missing_meta_credentials"}

    url = f"https://graph.facebook.com/v18.0/{phone_number_id}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": to_number,
        "type": "text",
        "text": {"body": body},
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as response:
            response_body = response.read().decode("utf-8")
            log_step("meta_send_success", status=getattr(response, "status", None), response_preview=response_body[:200])
            return {"sent": True, "response": response_body}
    except Exception as exc:
        log_step("meta_send_failure", error=str(exc)[:200])
        return {"sent": False, "reason": "graph_api_error", "detail": str(exc)}


def extract_message_from_payload(payload):
    try:
        entry = payload.get("entry", [])[0]
        changes = entry.get("changes", [])[0]
        value = changes.get("value", {})
        messages = value.get("messages", [])
        if not messages:
            return None, None, None
        msg = messages[0]
        sender = msg.get("from")
        msg_id = msg.get("id") or payload.get("object")
        text = None
        if isinstance(msg.get("text"), dict):
            text = msg.get("text", {}).get("body")
        else:
            text = msg.get("text")
        return msg_id, sender, text
    except Exception:
        return None, None, None


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "")
    log_step("webhook_request", method=method, path=path, query_string=environ.get("QUERY_STRING", "")[:200])

    if path != "/api/index":
        log_step("webhook_route_mismatch", expected="/api/index", actual=path)
        return json_response(start_response, {"error": "not found"}, status="404 Not Found")

    if method == "GET":
        params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        verify = params.get("hub.verify_token", [None])[0]
        challenge = params.get("hub.challenge", [None])[0]

        log_step("verify_token_check", verify_token_present=bool(verify), challenge_present=bool(challenge), expected_token_present=bool(VERIFY_TOKEN))
        if verify is None or challenge is None:
            return json_response(start_response, {"status": "ok", "note": "no verify token provided"})

        if verify != VERIFY_TOKEN:
            log_step("verify_token_mismatch", got=verify, expected=VERIFY_TOKEN)
            return json_response(start_response, {"error": "invalid verify token"}, status="403 Forbidden")

        start_response("200 OK", [("Content-Type", "text/plain")])
        log_step("verify_token_ok", challenge=challenge)
        return [challenge.encode("utf-8")]

    if method != "POST":
        log_step("unsupported_method", method=method)
        return json_response(start_response, {"error": "method not allowed"}, status="405 Method Not Allowed")

    try:
        content_length = int(environ.get("CONTENT_LENGTH", "0") or "0")
    except ValueError:
        content_length = 0

    body = environ["wsgi.input"].read(content_length) if content_length > 0 else environ["wsgi.input"].read()
    if not body:
        log_step("webhook_empty_body")
        return json_response(start_response, {"error": "empty request body"}, status="400 Bad Request")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        log_step("webhook_invalid_json", error=str(exc)[:200])
        return json_response(start_response, {"error": "invalid json", "detail": str(exc)}, status="400 Bad Request")

    msg_id, sender, text = extract_message_from_payload(payload)
    log_step("webhook_message_extracted", message_id=msg_id, sender=sender, body_preview=(text[:160] if text else ""))
    if sender is None or text is None:
        log_step("webhook_no_message", payload_keys=list(payload.keys())[:10])
        return json_response(start_response, {"error": "no message found in payload"}, status="400 Bad Request")

    agent_state = {
        "message_id": msg_id,
        "incoming_message": text,
        "sender_hash": hash_sender(sender),
        "thread_id": f"stage1-{msg_id}",
        "debug_trace": [],
    }
    log_step("agent_dispatch", thread_id=agent_state["thread_id"], message_id=msg_id, incoming_message_preview=text[:160])
    agent_result = run_agent(agent_state)
    log_step("agent_result", thread_id=agent_result.get("thread_id"), final_response_preview=(agent_result.get("final_response") or "")[:180], debug_trace_len=len(agent_result.get("debug_trace", [])))

    reply_text = agent_result.get("final_response") or "Message received."
    send_result = send_whatsapp_message(sender, reply_text)

    return json_response(
        start_response,
        {
            "reply": reply_text,
            "message_id": msg_id,
            "thread_id": agent_result.get("thread_id"),
            "whatsapp_sent": bool(send_result.get("sent")),
            "whatsapp_status": send_result.get("reason"),
            "debug_trace": agent_result.get("debug_trace", []),
        },
    )


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    port = int(os.environ.get("PORT", "3000"))
    print(f"Starting local test server on :{port} (path /api/index)")
    with make_server("0.0.0.0", port, app) as server:
        server.serve_forever()
