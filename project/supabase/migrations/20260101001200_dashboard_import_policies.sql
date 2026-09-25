-- Migration: 20260101001200_dashboard_import_policies.sql
-- Grant UPDATE on projects, DELETE on project_records, and INSERT/UPDATE/DELETE on project_field_definitions
-- to enable full Excel reconciliation and direct project creation from the dashboard.

-- 1. Table Grants
GRANT UPDATE ON public.projects TO app_backend;
GRANT DELETE ON public.project_records TO app_backend;
GRANT INSERT, UPDATE, DELETE ON public.project_field_definitions TO app_backend;

-- 2. Projects Update Policy
DROP POLICY IF EXISTS projects_update_backend ON public.projects;

CREATE POLICY projects_update_backend
    ON public.projects
    FOR UPDATE
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
    )
    WITH CHECK (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = projects.id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_approve_projects
        )
    );

-- 3. Project Records Delete Policy
DROP POLICY IF EXISTS project_records_delete_backend ON public.project_records;

CREATE POLICY project_records_delete_backend
    ON public.project_records
    FOR DELETE
    TO app_backend
    USING (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_records.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_add_rows
        )
    );

-- 4. Project Field Definitions Insert / Update / Delete Policies
DROP POLICY IF EXISTS project_field_definitions_insert_backend ON public.project_field_definitions;

CREATE POLICY project_field_definitions_insert_backend
    ON public.project_field_definitions
    FOR INSERT
    TO app_backend
    WITH CHECK (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_field_definitions.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    );

DROP POLICY IF EXISTS project_field_definitions_update_backend ON public.project_field_definitions;

CREATE POLICY project_field_definitions_update_backend
    ON public.project_field_definitions
    FOR UPDATE
    TO app_backend
    USING (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_field_definitions.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    )
    WITH CHECK (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_field_definitions.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    );

DROP POLICY IF EXISTS project_field_definitions_delete_backend ON public.project_field_definitions;

CREATE POLICY project_field_definitions_delete_backend
    ON public.project_field_definitions
    FOR DELETE
    TO app_backend
    USING (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_field_definitions.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    );
