-- Phase 1, step 5: user_project_access
-- This is the permission table every RLS policy in this project
-- ultimately keys off of, alongside services/authorization.py.

create table if not exists public.user_project_access (
    id                     uuid primary key default gen_random_uuid(),
    user_id                uuid not null references public.agent_users(id) on delete cascade,
    project_id             uuid not null references public.projects(id) on delete cascade,
    can_read               boolean not null default true,
    can_add_rows           boolean not null default false,
    can_propose_fields     boolean not null default false,
    can_approve_fields     boolean not null default false,
    can_propose_projects   boolean not null default false,
    can_approve_projects   boolean not null default false,
    created_at             timestamptz not null default now(),
    unique (user_id, project_id)
);

alter table public.user_project_access enable row level security;

grant select on public.user_project_access to app_backend;
-- No insert/update grant for app_backend: granting or changing a user's
-- project access is an administrative action (or the transactional
-- creator-access step inside create_project's own transaction, which
-- runs under the service_role admin path in services/database.py, not
-- as app_backend). Keeping this grant read-only for app_backend closes
-- off a whole class of privilege-escalation bugs where a compromised
-- tool could grant itself access.

create policy user_project_access_select_self
    on public.user_project_access
    for select
    to app_backend
    using (user_id = nullif(current_setting('app.current_user_id', true), '')::uuid);

-- ---------------------------------------------------------------------
-- Now that user_project_access exists, add the policies that were
-- deferred on project_records, project_field_definitions, and
-- chat_sessions. Kept in this file (rather than the later
-- row_policies.sql) since it's the natural place once this table exists
-- -- row_policies.sql is reserved for agent_runs/agent_events/
-- pending_approvals/processed_messages, which depend on agent_users too
-- but come later in table order.
-- ---------------------------------------------------------------------

create policy project_records_select_with_access
    on public.project_records
    for select
    to app_backend
    using (
        exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_records.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    );

create policy project_records_insert_with_access
    on public.project_records
    for insert
    to app_backend
    with check (
        exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_records.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_add_rows
        )
    );

create policy project_field_definitions_select_with_access
    on public.project_field_definitions
    for select
    to app_backend
    using (
        exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_field_definitions.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    );

create policy project_field_definitions_insert_with_access
    on public.project_field_definitions
    for insert
    to app_backend
    with check (
        exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_field_definitions.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_propose_fields
        )
    );
-- Note: this policy allows the INSERT once the requester has
-- can_propose_fields -- it does not know or care whether admin approval
-- has already happened. That check (pending_approvals.status =
-- 'approved') is enforced in services/approvals.py before the tool ever
-- attempts this insert. RLS here guards against inserting on behalf of a
-- project the user has no relationship to at all, not against skipping
-- the approval workflow -- that's an application-layer guarantee, not a
-- database-layer one, because "has an approved pending_approvals row"
-- isn't expressible as a static policy without a bigger query.

create policy chat_sessions_select_self
    on public.chat_sessions
    for select
    to app_backend
    using (user_id = nullif(current_setting('app.current_user_id', true), '')::uuid);

create policy chat_sessions_insert_self
    on public.chat_sessions
    for insert
    to app_backend
    with check (user_id = nullif(current_setting('app.current_user_id', true), '')::uuid);
