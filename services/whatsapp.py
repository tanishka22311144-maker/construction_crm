import os
import httpx
from typing import Dict, Any

# ----------------------------------------------------------------------
# WHATSAPP CLOUD API CREDENTIALS
# ----------------------------------------------------------------------
def send_whatsapp_message(recipient: str, message: str) -> Dict[str, Any]:
    """Send a plain-text WhatsApp message via the Cloud API.

    Args:
        recipient: Phone number in international format (e.g. "15551234567").
        message: Text body to send.

    Returns:
        Parsed JSON response or status dict.
    """
    token = os.getenv("META_WHATSAPP_TOKEN") or os.getenv("META_ACCESS_TOKEN") or os.getenv("WHATSAPP_TOKEN") or ""
    phone_number_id = os.getenv("META_PHONE_NUMBER_ID") or os.getenv("WHATSAPP_PHONE_NUMBER_ID") or ""

    if not (token and phone_number_id and recipient):
        return {
            "status": "skipped",
            "reason": "missing credentials or recipient",
            "has_token": bool(token),
            "has_phone_number_id": bool(phone_number_id),
            "has_recipient": bool(recipient),
        }

    url = f"https://graph.facebook.com/v20.0/{phone_number_id}/messages"
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": message},
    }
    try:
        resp = httpx.post(url, json=payload, headers=headers, timeout=15.0)
        resp.raise_for_status()
        return resp.json()
    except Exception as exc:
        return {"status": "error", "error": str(exc)}

