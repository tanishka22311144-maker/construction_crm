-- Allow app_backend to register new approvers and update display names
-- Required for dashboard WhatsApp login and admin self-registration
grant insert, update on public.agent_users to app_backend;

create policy agent_users_insert_backend
    on public.agent_users
    for insert
    to app_backend
    with check (true);

create policy agent_users_update_backend
    on public.agent_users
    for update
    to app_backend
    using (true)
    with check (true);
