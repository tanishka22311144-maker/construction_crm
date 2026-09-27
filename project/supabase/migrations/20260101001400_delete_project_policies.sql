-- Migration: 20260101001400_delete_project_policies.sql
-- Grant DELETE on public.projects to app_backend and define RLS delete policy.

GRANT DELETE ON public.projects TO app_backend;

DROP POLICY IF EXISTS projects_delete_backend ON public.projects;

CREATE POLICY projects_delete_backend
    ON public.projects
    FOR DELETE
    TO app_backend
    USING (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = projects.id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_approve_projects
        )
    );
