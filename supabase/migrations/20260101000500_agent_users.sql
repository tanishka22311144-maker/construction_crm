-- Phase 1, step 4: agent_users
-- This is the ONLY identity anchor in the system. There is no separate
-- verification/auth-challenge table or column by design -- see
-- .github/instructions/security.instructions.md. A WhatsApp sender IS
-- this row once whatsapp_sender_hash matches and is_active is true.

create table if not exists public.agent_users (
    id                     uuid primary key default gen_random_uuid(),
    whatsapp_sender_hash   text not null unique,
    display_name           text,
    role                   text not null
                             check (role in ('field_worker', 'site_supervisor', 'project_admin', 'finance_approver', 'system_admin')),
    is_active              boolean not null default true,
    created_at             timestamptz not null default now()
);

comment on table public.agent_users is
    'whatsapp_sender_hash = sha256 of the WhatsApp number. Never store the raw number here or anywhere else.';

alter table public.agent_users enable row level security;

-- The backend needs to look itself up by hash on every incoming message,
-- and register/deactivate users administratively. No public/anon access
-- at all -- app_backend only.
grant select on public.agent_users to app_backend;
-- Deliberately no insert/update grant for app_backend: new users and role
-- changes go through an out-of-band admin process (e.g. a Supabase
-- Studio action or a separate reviewed admin script using service_role),
-- never through a WhatsApp message. This is a hard line, not a
-- convenience gap -- do not add an insert/update grant here to make a
-- "self-registration" flow easier.

create policy agent_users_select_self_only
    on public.agent_users
    for select
    to app_backend
    using (
        whatsapp_sender_hash = current_setting('app.current_sender_hash', true)
        or id = nullif(current_setting('app.current_user_id', true), '')::uuid
    );
-- Note: the very first lookup of a request (resolving a sender hash to a
-- user_id before app.current_user_id is known) must set
-- app.current_sender_hash for this policy to allow the read. See
-- supabase/README.md for the exact session-variable sequence
-- services/database.py must follow per request.

-- ---------------------------------------------------------------------
-- Deferred foreign keys now that agent_users exists.
-- ---------------------------------------------------------------------

alter table public.projects
    add constraint projects_created_by_fkey
    foreign key (created_by) references public.agent_users(id);

alter table public.project_records
    add constraint project_records_created_by_fkey
    foreign key (created_by) references public.agent_users(id);

alter table public.project_field_definitions
    add constraint project_field_definitions_created_by_fkey
    foreign key (created_by) references public.agent_users(id);

alter table public.chat_sessions
    add constraint chat_sessions_user_id_fkey
    foreign key (user_id) references public.agent_users(id);
