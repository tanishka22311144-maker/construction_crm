-- Migration: 20260101001100_dashboard_rls_policies.sql
-- Allow dashboard and backend system queries (where app.current_user_id is unset)
-- to read project_records and project_field_definitions, while preserving
-- strict user-level access gating when a WhatsApp sender is bound.

-- 1. Table Grants
GRANT SELECT, INSERT, UPDATE ON public.project_records TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.project_records TO postgres, service_role;

GRANT SELECT, INSERT ON public.project_field_definitions TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.project_field_definitions TO postgres, service_role;

-- 2. Project Records Select Policy
DROP POLICY IF EXISTS project_records_select_own_access ON public.project_records;
DROP POLICY IF EXISTS project_records_select_with_access ON public.project_records;
DROP POLICY IF EXISTS project_records_select_backend ON public.project_records;

CREATE POLICY project_records_select_backend
    ON public.project_records
    FOR SELECT
    TO app_backend
    USING (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_records.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_read
        )
    );

-- 3. Project Records Update Policy (for dashboard spreadsheet edits)
DROP POLICY IF EXISTS project_records_update_backend ON public.project_records;

CREATE POLICY project_records_update_backend
    ON public.project_records
    FOR UPDATE
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
    )
    WITH CHECK (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_records.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_add_rows
        )
    );

-- 4. Project Records Insert Policy (for dashboard new rows & WhatsApp bot)
DROP POLICY IF EXISTS project_records_insert_with_access ON public.project_records;
DROP POLICY IF EXISTS project_records_insert_backend ON public.project_records;

CREATE POLICY project_records_insert_backend
    ON public.project_records
    FOR INSERT
    TO app_backend
    WITH CHECK (
        nullif(current_setting('app.current_user_id', true), '') is null
        OR exists (
            select 1
            from public.user_project_access upa
            where upa.project_id = project_records.project_id
              and upa.user_id = nullif(current_setting('app.current_user_id', true), '')::uuid
              and upa.can_add_rows
        )
    );

-- 5. Project Field Definitions Select Policy
DROP POLICY IF EXISTS project_field_definitions_select_own_access ON public.project_field_definitions;
DROP POLICY IF EXISTS project_field_definitions_select_backend ON public.project_field_definitions;

CREATE POLICY project_field_definitions_select_backend
    ON public.project_field_definitions
    FOR SELECT
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
