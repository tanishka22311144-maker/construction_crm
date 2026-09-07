-- Phase 1, step 2: project_records
-- created_by FK to agent_users is added later (see agent_users migration).

create table if not exists public.project_records (
    id           uuid primary key default gen_random_uuid(),
    project_id   uuid not null references public.projects(id) on delete cascade,
    record_type  text not null check (record_type in ('daily_log', 'expense', 'equipment_log')),
    record_date  date not null,
    title        text,
    description  text,
    amount       numeric(14, 2),
    unit         text,
    data         jsonb not null default '{}'::jsonb,
    created_by   uuid,
    created_at   timestamptz not null default now(),
    updated_at   timestamptz not null default now()
);

comment on table public.project_records is
    'Domain rows for daily logs, expenses, and equipment logs, distinguished by record_type. Governed by project_field_definitions rather than a fixed schema.';

create index if not exists project_records_project_type_date_idx
    on public.project_records (project_id, record_type, record_date desc);

alter table public.project_records enable row level security;

grant select, insert on public.project_records to app_backend;
-- No update/delete: the tools spec (add_project_row) only inserts.
-- Corrections, if ever supported, are a separate reviewed feature, not a
-- default capability of the WhatsApp agent.

-- RLS is enabled here so no row is readable/writable until a policy
-- explicitly allows it, but the actual policies are defined in
-- 20260101001000_row_policies.sql, once user_project_access (step 6)
-- exists -- policies can't reference a table that doesn't exist yet.
-- Until that migration runs, this table is correctly locked down to
-- nothing rather than silently wide open.
