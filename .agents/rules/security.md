<!-- Applies to: project/services/authorization.py, project/services/approvals.py, project/services/verification.py, project/services/database.py -->

# Security rules

- There is no separate identity-verification step in this system by
  design. `whatsapp_sender_hash` matched against an active `agent_users`
  row IS the identity. Do not add OTP, magic links, or any other auth
  factor without an explicit spec change — but do NOT weaken the
  authorization checks that already exist (role, `user_project_access`)
  on the theory that "verification was removed."
- The approval flow (`services/approvals.py`) is the one place a forged
  message would matter most, since WhatsApp is the only approval UI.
  Every approval decision must check ALL of: active `agent_users` row,
  correct `can_approve_*` permission for the project/operation, a valid
  unexpired `approval_id` referencing a `pending_approvals` row with
  `status = pending`, and `approval_token_hash` matching the stored value.
  Missing any one of these is a `REJECT`, not a warning.
- Never accept a bare "yes"/"approve" without an `approval_id` — even from
  a sender who otherwise has approval rights.
- `service_role` Supabase clients are instantiated only inside
  `project/services/database.py`'s admin-transaction path, never in tool
  code, never in graph nodes directly (PROJECT_SPEC.md §13).
- `authorize()` must be called before any service-role write, even when
  the caller believes the operation is already permission-checked
  upstream — treat it as defense in depth, not a redundant call to remove.
- The approval checklist in PROJECT_SPEC.md §11 is the full list — sender
  is an active `agent_users` row, role/`user_project_access` grants the
  specific `can_approve_*`, a valid unexpired `approval_id` against
  `pending_approvals.status = pending`, `approval_token_hash` match, and
  a payload-hash match against `proposed_payload`. All five, every time.
