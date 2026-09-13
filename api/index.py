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

from agent.graph import run_agent

VERIFY_TOKEN = os.environ.get("VERIFY_TOKEN", "dev-verify-token")


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
    if not access_token or not phone_number_id:
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
            return {"sent": True, "response": response_body}
    except Exception as exc:
        return {"sent": False, "reason": "graph_api_error", "detail": str(exc)}


def extract_message_from_payload(payload):
    try:
        entries = payload.get("entry", [])
        for entry in entries:
            changes = entry.get("changes", [])
            for change in changes:
                value = change.get("value", {})
                messages = value.get("messages") or []
                if not messages:
                    continue
                msg = messages[0]
                sender = msg.get("from")
                msg_id = msg.get("id") or payload.get("object")
                text = msg.get("text")
                if isinstance(text, dict):
                    text = text.get("body")
                if sender is None or text is None:
                    continue
                return msg_id, sender, str(text).strip()
        return None, None, None
    except Exception:
        return None, None, None


def app(environ, start_response):
    method = environ.get("REQUEST_METHOD", "GET").upper()
    path = environ.get("PATH_INFO", "")

    if path != "/api/index":
        return json_response(start_response, {"error": "not found"}, status="404 Not Found")

    if method == "GET":
        params = urllib.parse.parse_qs(environ.get("QUERY_STRING", ""))
        verify = params.get("hub.verify_token", [None])[0]
        challenge = params.get("hub.challenge", [None])[0]

        if verify is None or challenge is None:
            return json_response(start_response, {"status": "ok", "note": "no verify token provided"})

        if verify != VERIFY_TOKEN:
            return json_response(start_response, {"error": "invalid verify token"}, status="403 Forbidden")

        start_response("200 OK", [("Content-Type", "text/plain")])
        return [challenge.encode("utf-8")]

    if method != "POST":
        return json_response(start_response, {"error": "method not allowed"}, status="405 Method Not Allowed")

    try:
        content_length = int(environ.get("CONTENT_LENGTH", "0") or "0")
    except ValueError:
        content_length = 0

    body = environ["wsgi.input"].read(content_length) if content_length > 0 else environ["wsgi.input"].read()
    if not body:
        return json_response(start_response, {"error": "empty request body"}, status="400 Bad Request")

    try:
        payload = json.loads(body.decode("utf-8"))
    except Exception as exc:
        return json_response(start_response, {"error": "invalid json", "detail": str(exc)}, status="400 Bad Request")

    msg_id, sender, text = extract_message_from_payload(payload)
    if sender is None or text is None:
        return json_response(
            start_response,
            {"status": "ignored", "reason": "no_message_found_in_payload"},
            status="200 OK",
        )

    agent_state = {
        "message_id": msg_id,
        "incoming_message": text,
        "sender_hash": hash_sender(sender),
        "thread_id": f"stage1-{msg_id}",
    }
    agent_result = run_agent(agent_state)
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
        },
    )


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    port = int(os.environ.get("PORT", "3000"))
    print(f"Starting local test server on :{port} (path /api/index)")
    with make_server("0.0.0.0", port, app) as server:
        server.serve_forever()

