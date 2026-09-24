-- Migration: 20260101001000_create_project_permissions.sql
-- Fix permissions and RLS policies for create_project onboarding workflow:
-- 1. Table grants: allow app_backend to insert into projects and user_project_access
-- 2. RLS policies on public.projects: allow select and insert
-- 3. RLS policies on public.project_field_definitions: allow insert
-- 4. RLS policies on public.user_project_access: allow insert and update

-- 1. Table Grants
GRANT SELECT, INSERT ON public.projects TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.projects TO postgres, service_role;

GRANT SELECT, INSERT, UPDATE ON public.user_project_access TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.user_project_access TO postgres, service_role;

GRANT SELECT, INSERT ON public.project_field_definitions TO app_backend;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.project_field_definitions TO postgres, service_role;

-- 2. Projects RLS policies
DROP POLICY IF EXISTS projects_select_own_access ON public.projects;
DROP POLICY IF EXISTS projects_select_app_backend ON public.projects;
CREATE POLICY projects_select_app_backend
    ON public.projects
    FOR SELECT
    TO app_backend
    USING (true);

DROP POLICY IF EXISTS projects_insert_app_backend ON public.projects;
CREATE POLICY projects_insert_app_backend
    ON public.projects
    FOR INSERT
    TO app_backend
    WITH CHECK (true);

-- 3. Project Field Definitions RLS policies
DROP POLICY IF EXISTS project_field_definitions_insert_app_backend ON public.project_field_definitions;
CREATE POLICY project_field_definitions_insert_app_backend
    ON public.project_field_definitions
    FOR INSERT
    TO app_backend
    WITH CHECK (true);

-- 4. User Project Access RLS policies
DROP POLICY IF EXISTS user_project_access_insert_app_backend ON public.user_project_access;
CREATE POLICY user_project_access_insert_app_backend
    ON public.user_project_access
    FOR INSERT
    TO app_backend
    WITH CHECK (true);

DROP POLICY IF EXISTS user_project_access_update_app_backend ON public.user_project_access;
CREATE POLICY user_project_access_update_app_backend
    ON public.user_project_access
    FOR UPDATE
    TO app_backend
    USING (true)
    WITH CHECK (true);
