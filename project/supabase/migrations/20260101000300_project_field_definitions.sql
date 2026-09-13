-- Phase 1, step 3: project_field_definitions
-- created_by FK to agent_users is added later (see agent_users migration).

create table if not exists public.project_field_definitions (
    id                uuid primary key default gen_random_uuid(),
    project_id        uuid not null references public.projects(id) on delete cascade,
    record_type       text not null check (record_type in ('daily_log', 'expense', 'equipment_log')),
    field_name        text not null,
    field_type        text not null check (field_type in ('text', 'integer', 'numeric', 'boolean', 'date', 'enum')),
    required          boolean not null default false,
    default_value     jsonb,
    validation_rules  jsonb not null default '{}'::jsonb,
    created_by        uuid,
    created_at        timestamptz not null default now(),
    unique (project_id, record_type, field_name)
);

comment on table public.project_field_definitions is
    'Governed, per-project field schema for each record_type. create_project_field only ever inserts here -- it never issues DDL against project_records.';

alter table public.project_field_definitions enable row level security;

grant select, insert on public.project_field_definitions to app_backend;
-- No update/delete: a field definition is corrected by proposing a new
-- one through the same governed, approved path, not by silently mutating
-- history that agent_events may already reference.

-- Policies (dependent on user_project_access) are added in
-- 20260101001000_row_policies.sql. RLS is enabled now, so this table is
-- locked to nothing until that migration runs.
