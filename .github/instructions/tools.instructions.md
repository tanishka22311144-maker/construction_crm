---
description: 'Rules for implementing the four business tools'
applyTo: 'tools/**'
---

# Tool implementation instructions

Before writing any query here, read `supabase/README.md` — every tool
runs inside the per-request session-variable context it describes
(`app.current_user_id` etc.), and a tool that queries Supabase outside
that context will see zero rows from RLS rather than an error, which is
easy to misdiagnose as a permissions bug in your own code instead of a
missing `bind_request_context()` call upstream.

- Exactly four tools exist: `read_project_data`, `add_project_row`,
  `create_project_field`, `create_project`. Do not add a fifth without
  updating PROJECT_SPEC.md first — the risk/approval model in
  `services/authorization.py` is keyed off this fixed list.
- The LLM never supplies SQL, table names, or column names directly.
  Tool input schemas (`tools/schemas.py`) take `project_name` and
  domain-shaped fields; resolution to `project_id` and validation against
  `project_field_definitions` happens in the tool implementation.
- Every write tool (`add_project_row`, `create_project_field`,
  `create_project`) must return the strict result envelope from
  `.github/skills/verification-envelope/SKILL.md` and perform its own
  read-back before returning. Do not treat "no exception raised" or an
  HTTP 200 from the Supabase client as success.
- `limit` on `read_project_data` is always clamped server-side to 50,
  regardless of what's requested.
- Idempotency: every write tool call must compute and check the
  idempotency key described in `.github/skills/idempotency-key/SKILL.md`
  before inserting.
- Conditional-approval thresholds (expense amount, `can_add_rows`, etc.)
  belong in `services/authorization.py`, not hardcoded inside a tool file.
