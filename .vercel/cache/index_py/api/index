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
        return json_response(start_response, {"error": "no message found in payload"}, status="400 Bad Request")

    agent_state = {
        "message_id": msg_id,
        "incoming_message": text,
        "sender_hash": hash_sender(sender),
        "thread_id": f"stage1-{msg_id}",
    }
    agent_result = run_agent(agent_state)
    reply_text = agent_result.get("final_response") or "Message received."

    return json_response(
        start_response,
        {
            "reply": reply_text,
            "message_id": msg_id,
            "thread_id": agent_result.get("thread_id"),
        },
    )


if __name__ == "__main__":
    from wsgiref.simple_server import make_server

    port = int(os.environ.get("PORT", "3000"))
    print(f"Starting local test server on :{port} (path /api/index)")
    with make_server("0.0.0.0", port, app) as server:
        server.serve_forever()
