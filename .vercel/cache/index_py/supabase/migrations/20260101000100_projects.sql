-- Phase 1, step 1: projects
-- NOTE: created_by will reference agent_users(id), but agent_users doesn't
-- exist yet (it's step 4). The FK is added in
-- 20260101000400_agent_users.sql once the target table exists. This is a
-- deliberate ordering choice, not an oversight.

create table if not exists public.projects (
    id            uuid primary key default gen_random_uuid(),
    project_name  text not null,
    project_code  text not null unique,
    location      text,
    status        text not null default 'planned'
                    check (status in ('planned', 'active', 'completed', 'on_hold', 'cancelled')),
    created_by    uuid,
    created_at    timestamptz not null default now()
);

comment on table public.projects is
    'One row per construction project. No physical table is ever created per project — record_type rows in project_records carry the domain data.';

-- RLS + grants live in the same migration as table creation, per
-- .github/skills/supabase-rls/SKILL.md. There is no Supabase Auth user
-- here (WhatsApp senders aren't Supabase Auth users), so policies key off
-- a session-local setting the backend sets per request rather than
-- auth.uid(). See supabase/README.md for how services/database.py must
-- set this.

alter table public.projects enable row level security;

-- Dedicated non-service role used by the Vercel backend for all
-- non-administrative reads/writes. Created once; safe to re-run.
do $$
begin
    if not exists (select 1 from pg_roles where rolname = 'app_backend') then
        create role app_backend nologin;
    end if;
end
$$;

grant select, insert on public.projects to app_backend;
-- No update/delete grant: projects are not mutated or removed by the
-- runtime agent. Status changes, if ever needed, go through a reviewed
-- admin path, not the WhatsApp agent's normal write tools.

-- Any authenticated app_backend request can read a project's existence
-- (needed to resolve project_name -> project_id before permission checks
-- run) but only an admin-role user can see the row when access hasn't
-- been explicitly granted via user_project_access. We keep this simple
-- and permissive at the "does this project exist" level, since the real
-- gate is user_project_access on project_records reads below -- knowing
-- a project name/status exists is low-risk on its own.
create policy projects_select_app_backend
    on public.projects
    for select
    to app_backend
    using (true);

create policy projects_insert_app_backend
    on public.projects
    for insert
    to app_backend
    with check (true);
-- Insert-time authorization (can_propose_projects, approval requirement)
-- is enforced in services/authorization.py and the create_project tool,
-- not here -- this policy only says "the backend role, not the public,
-- may attempt this," matching the grants-vs-policy split described in
-- PROJECT_SPEC.md §13.
