-- Update UPDATE policy on pending_approvals to ensure app_backend can update status
DROP POLICY IF EXISTS pending_approvals_decide_as_matching_approver ON public.pending_approvals;

CREATE POLICY pending_approvals_decide_as_matching_approver
    ON public.pending_approvals
    FOR UPDATE
    TO app_backend
    USING (
        status = 'pending'
        AND (
            nullif(current_setting('app.current_user_id', true), '') IS NULL
            OR EXISTS (
                SELECT 1
                FROM public.agent_users u
                WHERE (
                    u.id = nullif(current_setting('app.current_user_id', true), '')::uuid
                    OR u.whatsapp_sender_hash = current_setting('app.current_sender_hash', true)
                )
                AND (u.role = pending_approvals.required_approver_role OR u.role IN ('project_admin', 'system_admin'))
                AND u.is_active
            )
        )
    )
    WITH CHECK (
        decided_by IS NOT NULL
        OR decided_by = nullif(current_setting('app.current_user_id', true), '')::uuid
    );
