---
description: 'Schema, migrations, and RLS rules for Supabase tables'
applyTo: 'supabase/**,db/**,**/*migration*.sql,services/database.py,tools/**'
---

# Database instructions

The actual schema lives in `supabase/migrations/` — read
`supabase/README.md` first, it explains the session-variable RLS pattern
these migrations depend on (there's no Supabase Auth user here, so
policies don't use `auth.uid()`). Treat the migrations as the source of
truth for column names/types; PROJECT_SPEC.md §2 is the design doc they
were derived from.

- Table order matters — follow PROJECT_SPEC.md §2/§18 Phase 1 exactly:
  `projects`, `project_records`, `project_field_definitions`, `agent_users`,
  `user_project_access`, `agent_runs`, `agent_events`, `pending_approvals`,
  `processed_messages`.
- Every table gets RLS enabled and explicit grants in the same migration
  that creates it — never ship a table without both.
- `agent_users.whatsapp_sender_hash` is the sole identity anchor in this
  system (see security note in root instructions). Never add a plaintext
  phone number column to this or any other table.
- `create_project` and any migration touching more than one table must be
  wrapped in a transaction with explicit rollback on any failure — partial
  project creation is treated as a bug, not a warning.
- Foreign keys from `project_records` and `project_field_definitions` to
  `projects.id` are mandatory; do not allow orphaned records at the schema
  level even though the application layer also checks this.
- Do not create a physical Postgres table per construction project.
  `create_project_field` and `create_project` operate purely on the
  `project_field_definitions` / `projects` / `user_project_access` rows —
  never generate DDL at runtime.
