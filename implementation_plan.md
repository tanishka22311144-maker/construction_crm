# Fix WhatsApp Sender Identity Resolution & Outbound Reply

## Root Cause Analysis

1. **Identity Resolution Mismatch (`load_identity_not_found`)**:
   - When Meta delivers a WhatsApp webhook message, `messages[0].from` contains the sender's phone number as pure digits without a leading `+` (e.g. `"918698510857"`).
   - In `project/api/index.py`, SHA-256 hashing was performed on this raw value:
     `sha256("918698510857")` = `f428e3cebfbd9e2db6bd6d024b76441c753bab316b584fe013351d9a6acb0428`.
   - However, in Supabase `public.agent_users`, the test user (`5fcbf888-75b1-4c11-986f-8d57033c6d80`) was previously seeded with `sha256("+918698510857")` = `b89121a31487da29daa9fc6f3a276380a15083a6af049736512c7ba87c777394` (with the `+` sign).
   - Because `agent_users` uses Row Level Security (`whatsapp_sender_hash = current_setting('app.current_sender_hash', true)`), and the query filters by `whatsapp_sender_hash = %s`, the hash mismatch resulted in 0 rows returned (`load_identity_not_found`), leading to `authorize()` denying access with `Unauthenticated or unresolvable sender identity`.

2. **Missing Token for Outbound WhatsApp Reply (`send_whatsapp_reply_skipped`)**:
   - In `project/api/index.py`, `_send_whatsapp_reply` looked up `os.getenv("META_WHATSAPP_TOKEN")`.
   - In Vercel's environment variables (and in `.env`), the variable is named `META_ACCESS_TOKEN`.
   - As a result, `token` resolved to empty string and the reply was skipped with `missing token/phone_number_id/recipient`.

3. **Missing Project Access for Test User**:
   - In `public.user_project_access`, user `5fcbf888-75b1-4c11-986f-8d57033c6d80` did not have an explicit `can_read = true` grant for the `Metro Line Extension` project (`e42d5bb4-117f-4c63-99a9-8a013129e002`).

---

## Proposed Changes

### 1. Canonical Phone Normalization Service
Create a shared helper in `project/services/identity.py` (and mirror to `services/identity.py`):
- `canonicalize_whatsapp_number(raw: str) -> str`:
  - Strips all non-digits (`+`, spaces, dashes, parentheses).
  - Handles 10-digit Indian numbers (starting with 6-9) by prefixing `91` to match Meta's standard payload format.
  - Returns canonical digits-only string.
- `hash_whatsapp_number(raw: str) -> str`:
  - Computes SHA-256 of `canonicalize_whatsapp_number(raw)`.

### 2. Update Webhook Ingestion & Graph Nodes
- **`project/api/index.py`**:
  - Use `canonicalize_whatsapp_number` and `hash_whatsapp_number` when computing `sender_hash`.
  - Update `_send_whatsapp_reply` to check both `META_WHATSAPP_TOKEN` and `META_ACCESS_TOKEN`.
  - Update `verify_webhook` to check both `META_VERIFY_TOKEN` and `VERIFY_TOKEN`.
  - Add safe diagnostic logging: presence of environment variables (boolean flags only), sender hash (no phone number), and reply outcome.
- **`project/agent/nodes.py`**:
  - In `load_identity_and_memory`: ensure `sender_hash` is computed from `sender_wa_id` via `hash_whatsapp_number` if not already present.
  - Add safe diagnostic logging of `sender_hash` and lookup result (`matched` or `not_matched`).

### 3. Database Alignment via Supabase MCP Tool
- Update `public.agent_users` for user `5fcbf888-75b1-4c11-986f-8d57033c6d80`:
  - Set `whatsapp_sender_hash = 'f428e3cebfbd9e2db6bd6d024b76441c753bab316b584fe013351d9a6acb0428'`.
  - Set `role = 'project_admin'`.
  - Ensure `is_active = true`.
- Update `public.user_project_access`:
  - Insert or upsert access record for user `5fcbf888-75b1-4c11-986f-8d57033c6d80` on project `e42d5bb4-117f-4c63-99a9-8a013129e002` with `can_read = true`.

### 4. Vercel Environment Variables
- Add alias environment variables `META_WHATSAPP_TOKEN` and `META_VERIFY_TOKEN` in Vercel production to prevent any naming discrepancy.

### 5. Update Documentation & Progress
- Update `IMPLEMENTATION_STAGES.md` at the very beginning to document Stage 2 progress and status.

---

## Verification Plan

### Automated Tests
- Run existing test suite:
  ```bash
  python -m unittest discover -s project/tests -p "test_*.py"
  ```
- Run tests in root:
  ```bash
  python -m unittest discover -s tests -p "test_*.py"
  ```

### Live Vercel Verification
- Deploy changes: `git push origin master` and `vercel --prod`.
- Send a test webhook request to `https://construction-crm-pi.vercel.app/api/index` simulating a message from `918698510857`.
- Check Vercel logs:
  - Verify `load_identity_result` shows `result: "matched"`.
  - Verify `check_permission` shows `allowed: true`.
  - Verify `send_whatsapp_reply` does not fail with `missing token/phone_number_id/recipient`.
