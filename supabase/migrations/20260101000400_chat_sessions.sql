-- Phase 1, step ~3.5 (grouped with the core tables in PROJECT_SPEC.md §2).
-- user_id FK to agent_users and run_id FK to agent_runs are both added
-- later, since neither target table exists yet.

create table if not exists public.chat_sessions (
    id              uuid primary key default gen_random_uuid(),
    user_id         uuid not null,
    user_message    text not null,
    assistant_reply text,
    run_id          uuid,
    created_at      timestamptz not null default now()
);

comment on table public.chat_sessions is
    'Bounded conversational memory only -- load the latest 6-10 rows per user for multi-turn context. Never a source of truth for business facts; see PROJECT_SPEC.md §12.';

create index if not exists chat_sessions_user_created_idx
    on public.chat_sessions (user_id, created_at desc);

alter table public.chat_sessions enable row level security;

grant select, insert on public.chat_sessions to app_backend;

-- Policies added in 20260101001000_row_policies.sql once agent_users
-- exists. Locked to nothing until then.
