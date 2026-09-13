-- Phase 1, step 8: processed_messages
-- Backs webhook deduplication -- see PROJECT_SPEC.md §10 and
-- .github/skills/idempotency-key/SKILL.md. message_id is the Meta
-- webhook's own message identifier, so it is the primary key rather than
-- a separate uuid -- there is exactly one row per distinct inbound
-- message, which is the whole point of this table.

create table if not exists public.processed_messages (
    message_id    text primary key,
    sender_hash   text not null,
    status        text not null default 'processing'
                    check (status in ('processing', 'complete', 'failed')),
    run_id        uuid references public.agent_runs(id),
    processed_at  timestamptz not null default now()
);

create index if not exists processed_messages_sender_idx
    on public.processed_messages (sender_hash);

alter table public.processed_messages enable row level security;

grant select, insert, update on public.processed_messages to app_backend;
-- Update is needed to move a row from 'processing' to 'complete'/'failed'
-- and attach run_id once known.

-- Deliberately no per-user policy scoping here: the very first thing that
-- happens on any webhook call is checking processed_messages BEFORE
-- app.current_user_id is known (identity resolution happens after
-- dedup, not before -- see the graph order in PROJECT_SPEC.md §5). A
-- policy requiring current_user_id would deadlock the dedup check on
-- every single message. app_backend is a private, non-login role only
-- the server ever connects as, so table-level grants are the right
-- boundary here rather than a row policy.
create policy processed_messages_backend_all
    on public.processed_messages
    for all
    to app_backend
    using (true)
    with check (true);
