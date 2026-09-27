-- 20260101001300_new_standard_sheets.sql
-- Expand check constraints for new standard sheets:
-- material_procurement, expense, manpower_equipment, daily_work_done
-- while preserving legacy daily_log and equipment_log for backward compatibility.

DO $$
BEGIN
    -- Drop old check constraint on project_records if it exists
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'project_records_record_type_check'
    ) THEN
        ALTER TABLE public.project_records DROP CONSTRAINT project_records_record_type_check;
    END IF;

    -- Add updated check constraint to project_records
    ALTER TABLE public.project_records
        ADD CONSTRAINT project_records_record_type_check
        CHECK (record_type IN ('material_procurement', 'expense', 'manpower_equipment', 'daily_work_done', 'daily_log', 'equipment_log'));

    -- Drop old check constraint on project_field_definitions if it exists
    IF EXISTS (
        SELECT 1 FROM pg_constraint WHERE conname = 'project_field_definitions_record_type_check'
    ) THEN
        ALTER TABLE public.project_field_definitions DROP CONSTRAINT project_field_definitions_record_type_check;
    END IF;

    -- Add updated check constraint to project_field_definitions
    ALTER TABLE public.project_field_definitions
        ADD CONSTRAINT project_field_definitions_record_type_check
        CHECK (record_type IN ('material_procurement', 'expense', 'manpower_equipment', 'daily_work_done', 'daily_log', 'equipment_log'));
END $$;
