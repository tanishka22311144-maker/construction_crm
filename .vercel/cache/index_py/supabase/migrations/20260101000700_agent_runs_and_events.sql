-- Phase 1, step 6: agent_runs, agent_events
-- These are append-mostly audit tables -- see PROJECT_SPEC.md §15.

create table if not exists public.agent_runs (
    id              uuid primary key default gen_random_uuid(),
    thread_id       text not null,
    user_id         uuid references public.agent_users(id),
    message_id      text not null,
    status          text not null default 'running'
                      check (status in ('running', 'waiting_approval', 'completed', 'failed')),
    intent          text,
    current_node    text,
    retry_count     integer not null default 0,
    started_at      timestamptz not null default now(),
    completed_at    timestamptz,
    final_response  text,
    error_code      text,
    error_message   text
);

create index if not exists agent_runs_thread_idx on public.agent_runs (thread_id);
create index if not exists agent_runs_message_idx on public.agent_runs (message_id);

create table if not exists public.agent_events (
    id               uuid primary key default gen_random_uuid(),
    run_id           uuid not null references public.agent_runs(id) on delete cascade,
    sequence_number  integer not null,
    event_type       text not null,
    status           text,
    node_name        text,
    tool_name        text,
    input_json       jsonb,
    output_json      jsonb,
    decision_json    jsonb,
    error_json       jsonb,
    duration_ms      integer,
    created_at       timestamptz not null default now(),
    unique (run_id, sequence_number)
);

comment on table public.agent_events is
    'Durable record of what actually happened, per PROJECT_SPEC.md §15. Outlives LangSmith retention -- this is the permanent audit trail, LangSmith is the debugging/eval tool.';

alter table public.agent_runs enable row level security;
alter table public.agent_events enable row level security;

-- Runs/events are written by the graph on behalf of whichever user is
-- current, but must remain readable by that same session for the
-- duration of the run, and by nobody else through app_backend. Cross-run
-- reads (e.g. an admin dashboard) should go through the service_role
-- admin path, not app_backend.
grant select, insert, update on public.agent_runs to app_backend;
grant select, insert on public.agent_events to app_backend;
-- No update/delete on agent_events: it's an append-only log by design.
-- If a recorded event was wrong, record a correcting event -- never
-- rewrite history that other audit rows may reference.

create policy agent_runs_owner_only
    on public.agent_runs
    for all
    to app_backend
    using (user_id = nullif(current_setting('app.current_user_id', true), '')::uuid)
    with check (user_id = nullif(current_setting('app.current_user_id', true), '')::uuid);

create policy agent_events_owner_only
    on public.agent_events
    for all
    to app_backend
    using (
        exists (
            select 1 from public.agent_runs r
            where r.id = agent_events.run_id
              and r.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
        )
    )
    with check (
        exists (
            select 1 from public.agent_runs r
            where r.id = agent_events.run_id
              and r.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
        )
    );

-- Now that agent_runs exists, add the deferred FK from chat_sessions.
alter table public.chat_sessions
    add constraint chat_sessions_run_id_fkey
    foreign key (run_id) references public.agent_runs(id);
