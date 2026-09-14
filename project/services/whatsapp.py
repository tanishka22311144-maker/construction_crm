import os
import httpx
from typing import Dict, Any

# ----------------------------------------------------------------------
# WHATSAPP CLOUD API CREDENTIALS
# ----------------------------------------------------------------------
WHATSAPP_TOKEN = os.getenv("WHATSAPP_TOKEN")
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")

if not WHATSAPP_TOKEN or not WHATSAPP_PHONE_NUMBER_ID:
    raise RuntimeError(
        "WhatsApp credentials missing: set WHATSAPP_TOKEN and WHATSAPP_PHONE_NUMBER_ID"
    )

BASE_URL = f"https://graph.facebook.com/v17.0/{WHATSAPP_PHONE_NUMBER_ID}/messages"
HEADERS = {"Authorization": f"Bearer {WHATSAPP_TOKEN}", "Content-Type": "application/json"}

def send_whatsapp_message(recipient: str, message: str) -> Dict[str, Any]:
    """Send a plain‑text WhatsApp message via the Cloud API.

    Args:
        recipient: Phone number in international format (e.g. "15551234567").
        message: Text body to send.

    Returns:
        Parsed JSON response from the API.
    """
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient,
        "type": "text",
        "text": {"body": message},
    }
    resp = httpx.post(BASE_URL, json=payload, headers=HEADERS, timeout=15.0)
    resp.raise_for_status()
    return resp.json()
