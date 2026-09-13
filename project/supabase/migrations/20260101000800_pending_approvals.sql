-- Phase 1, step 7: pending_approvals
-- This table backs the WhatsApp-only approval flow in
-- .github/skills/whatsapp-approval-flow/SKILL.md and PROJECT_SPEC.md §11.
-- approval_token_hash is the one extra safeguard standing in for identity
-- verification -- do not remove it or make it optional.

create table if not exists public.pending_approvals (
    id                        uuid primary key default gen_random_uuid(),
    run_id                    uuid not null references public.agent_runs(id) on delete cascade,
    thread_id                 text not null,
    requested_by              uuid not null references public.agent_users(id),
    required_approver_role    text not null,
    operation                 text not null,
    proposed_payload          jsonb not null,
    status                    text not null default 'pending'
                                check (status in ('pending', 'approved', 'rejected', 'expired', 'edited')),
    approval_token_hash       text not null,
    requested_at              timestamptz not null default now(),
    expires_at                timestamptz not null,
    decided_by                uuid references public.agent_users(id),
    decision                  text,
    decision_reason           text,
    decided_at                timestamptz
);

create index if not exists pending_approvals_status_idx
    on public.pending_approvals (status) where status = 'pending';

alter table public.pending_approvals enable row level security;

grant select, insert, update on public.pending_approvals to app_backend;
-- Update is needed to record the decision (status, decided_by, decision,
-- decision_reason, decided_at) -- but see the policy below, which
-- restricts who can move a row out of 'pending'.

create policy pending_approvals_visible_to_requester_or_approver
    on public.pending_approvals
    for select
    to app_backend
    using (
        requested_by = nullif(current_setting('app.current_user_id', true), '')::uuid
        or exists (
            select 1
            from public.agent_users u
            where u.id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and u.role = pending_approvals.required_approver_role
              and u.is_active
        )
    );

create policy pending_approvals_insert_as_requester
    on public.pending_approvals
    for insert
    to app_backend
    with check (requested_by = nullif(current_setting('app.current_user_id', true), '')::uuid);

create policy pending_approvals_decide_as_matching_approver
    on public.pending_approvals
    for update
    to app_backend
    using (
        status = 'pending'
        and exists (
            select 1
            from public.agent_users u
            where u.id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and u.role = pending_approvals.required_approver_role
              and u.is_active
        )
    )
    with check (decided_by = nullif(current_setting('app.current_user_id', true), '')::uuid);
-- This policy enforces "only someone with the required role can move a
-- pending row." The full checklist in PROJECT_SPEC.md §11 (project-level
-- can_approve_* permission, unexpired, token hash match, payload hash
-- match) still belongs in services/approvals.py -- role match alone is
-- necessary but not sufficient, and this policy is not a substitute for
-- that full check.
