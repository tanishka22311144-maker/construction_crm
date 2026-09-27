-- Update SELECT policy on pending_approvals to allow dashboard admin view
DROP POLICY IF EXISTS pending_approvals_visible_to_requester_or_approver ON public.pending_approvals;

CREATE POLICY pending_approvals_visible_to_requester_or_approver
    ON public.pending_approvals
    FOR SELECT
    TO app_backend
    USING (
        nullif(current_setting('app.current_user_id', true), '') is null
        or requested_by = nullif(current_setting('app.current_user_id', true), '')::uuid
        or exists (
            select 1
            from public.agent_users u
            where (
                u.id = nullif(current_setting('app.current_user_id', true), '')::uuid
                or u.whatsapp_sender_hash = current_setting('app.current_sender_hash', true)
            )
            and (u.role = pending_approvals.required_approver_role or u.role in ('project_admin', 'system_admin'))
            and u.is_active
        )
    );
