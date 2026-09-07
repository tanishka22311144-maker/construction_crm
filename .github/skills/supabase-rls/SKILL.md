---
name: supabase-rls
description: RLS + grants pattern to apply to every new Supabase table in this project
---

# Supabase RLS pattern

For every table:

1. `ALTER TABLE <table> ENABLE ROW LEVEL SECURITY;` in the same migration
   that creates the table.
2. Grant only the operations the application actually needs to the role
   that will use it (never blanket `ALL` to `authenticated` for
   agent-facing tables — this system authorizes at the application layer
   via `authorize()`, and RLS is the second, DB-level line of defense, not
   a replacement for it).
3. Write policies scoped by `project_id` wherever the table has one —
   never a policy that lets a role read/write across all projects.
4. `service_role` bypasses RLS entirely. Any code path using it must call
   `authorize()` first regardless — see `.github/instructions/security.instructions.md`.
5. Never grant table access directly to an anonymous/public role. WhatsApp
   users never talk to Supabase directly; only the Vercel function does.

Checklist to paste into a PR description for any migration:

- [ ] RLS enabled
- [ ] Grants scoped to the minimum operations needed
- [ ] Policies filter by `project_id` where applicable
- [ ] No `service_role` key referenced outside `services/database.py`
