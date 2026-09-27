-- Grant DELETE on user_project_access to app_backend and define RLS policy for cascading deletions
GRANT DELETE ON public.user_project_access TO app_backend;

DROP POLICY IF EXISTS user_project_access_delete_app_backend ON public.user_project_access;

CREATE POLICY user_project_access_delete_app_backend
    ON public.user_project_access
    FOR DELETE
    TO app_backend
    USING (true);

-- Also ensure pending_approvals has DELETE grant
GRANT DELETE ON public.pending_approvals TO app_backend;
