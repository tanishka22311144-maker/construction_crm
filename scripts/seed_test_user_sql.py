# scripts/seed_test_user.py
import os, hashlib
from pathlib import Path
from supabase import create_client, Client

# Load .env (same logic as load_local_env)
env_path = Path(__file__).resolve().parents[2] / ".env"
if env_path.is_file():
    for line in env_path.read_text().splitlines():
        if line.strip() and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

SUPABASE_URL = os.getenv("SUPABASE_URL") or os.getenv("SUPABASE_DB_URL")
SERVICE_KEY  = os.getenv("SERVICE_ROLE_KEY")
TEST_WHATSAPP = os.getenv("TEST_WHATSAPP_NUMBER")  # e.g. your real phone

import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from services.identity import canonicalize_whatsapp_number, hash_whatsapp_number

if not all([SUPABASE_URL, SERVICE_KEY, TEST_WHATSAPP]):
    raise RuntimeError("Missing SUPABASE_URL, SERVICE_ROLE_KEY, or TEST_WHATSAPP_NUMBER")

sender_hash = hash_whatsapp_number(TEST_WHATSAPP)
client: Client = create_client(SUPABASE_URL, SERVICE_KEY)

existing = client.table("agent_users").select("id").eq("whatsapp_sender_hash", sender_hash).execute()
if existing.data:
    print(f"Test user already exists: {existing.data[0]['id']}")
else:
    payload = {
        "whatsapp_sender_hash": sender_hash,
        "display_name": "Test User",
        "role": "admin",
        "is_active": True,
    }
    resp = client.table("agent_users").insert(payload).execute()
    print("Inserted test user:", resp.data)