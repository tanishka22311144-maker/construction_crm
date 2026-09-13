# Supabase schema

Run these migrations in order (they're numbered/timestamped so `supabase
db push` or the CLI's migration runner applies them correctly). Each one
creates a table, enables RLS, and grants the minimum operations to a
dedicated `app_backend` role in the same file — per
`.github/skills/supabase-rls/SKILL.md`. Foreign keys and policies that
depend on a table created later in the sequence are added once that table
exists (search each file for "deferred" if you want to trace exactly
where).

## Why this isn't the usual Supabase Auth + `auth.uid()` pattern

WhatsApp senders never log into Supabase — there's no Supabase Auth user,
no JWT, no `auth.uid()`. Identity is `agent_users.whatsapp_sender_hash`,
resolved by the backend itself (see
`.github/instructions/security.instructions.md`). So instead of RLS
policies checking `auth.uid()`, they check **session-local Postgres
settings** that `services/database.py` must set at the start of every
request, before running any query:

```python
# services/database.py, at the start of handling a request, on the
# connection/transaction that will run for this request's queries:

def bind_request_context(conn, sender_hash: str | None, user_id: str | None):
    with conn.cursor() as cur:
        # set_config(..., is_local=True) scopes this to the current
        # transaction only -- it does NOT leak into the connection pool's
        # next borrower. Never use SET (without LOCAL) here.
        cur.execute(
            "select set_config('app.current_sender_hash', %s, true)",
            (sender_hash or "",),
        )
        cur.execute(
            "select set_config('app.current_user_id', %s, true)",
            (user_id or "",),
        )
```

Sequence per request:

1. Webhook arrives. Before identity is known, only
   `app.current_sender_hash` can be set (from the raw WhatsApp payload,
   hashed). This is enough to satisfy `agent_users_select_self_only` in
   `20260101000500_agent_users.sql` so the backend can look itself up.
   `processed_messages` dedup doesn't need either variable — see the note
   in `20260101000900_processed_messages.sql` for why that table's policy
   is intentionally not per-user.
2. Once `load_identity_and_memory` resolves a matching, active
   `agent_users` row, set `app.current_user_id` to that row's `id` for
   the rest of the request. Every subsequent policy (`project_records`,
   `project_field_definitions`, `chat_sessions`, `agent_runs`,
   `agent_events`, `pending_approvals`) keys off this.
3. If no match is found, leave `app.current_user_id` unset. Every policy
   that requires it will then correctly deny all rows — this is what
   makes an unregistered sender fail closed rather than needing a
   separate "is this a valid user" check duplicated in application code.

**This is a second line of defense, not a replacement for
`services/authorization.py`.** The application must still call
`authorize()` before every operation. The point of these policies is that
if a future code change ever forgets to call `authorize()`, or gets the
check subtly wrong, the database itself still won't return or accept rows
the session variables don't justify.

## Roles

- `app_backend` — the only role the Vercel function connects as for
  normal request handling. `nologin` at the Postgres level in the sense
  that nothing outside the pooled backend connection should ever
  authenticate as it directly; scope its actual login/connection string
  the same way you'd scope any other backend DB credential.
- `service_role` — Supabase's built-in role that bypasses RLS entirely.
  Used ONLY inside `services/database.py`'s restricted admin-transaction
  path, for the multi-table transactional writes in `create_project` and
  the field-definition insert after approval in `create_project_field`.
  Even there, `authorize()` must run first — RLS bypass is not a shortcut
  around application-level permission checks, it's just necessary because
  a single logical operation spans tables with different per-row owners
  and no single `app_backend` policy could express "insert here AND here
  AND here as one unit" cleanly.

## What's NOT here yet

These migrations create structure only. Still needed before Phase 1 is
actually done, per PROJECT_SPEC.md §18:

- Seed data for local/dev testing (a sample project, a sample
  `agent_users` row matching your own test WhatsApp number's hash, matching
  `user_project_access`).
- The actual Postgres connection/pooling setup in
  `services/database.py` that calls `bind_request_context()` above.
- LangGraph's own Postgres checkpointer tables — those are created by
  LangGraph's checkpointer library itself (`langgraph-checkpoint-postgres`)
  when it first connects with a `setup()` call, not by a migration file
  here. Point it at the same Supabase Postgres instance but treat its
  tables as LangGraph-owned, not part of this schema.
