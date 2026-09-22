"""Tool: create_project_field for adding governed custom field definitions.

Per PROJECT_SPEC.md §6 Tool 3 and .agents/skills/verification-envelope/SKILL.md:
Inserts a row into project_field_definitions rather than issuing DDL against project_records.
"""
import json
from typing import Any, Optional
import uuid

from services.database import execute_query


ALLOWED_FIELD_TYPES = {"text", "integer", "numeric", "boolean", "date", "enum"}
ALLOWED_RECORD_TYPES = {"daily_log", "expense", "equipment_log"}


def create_project_field(
    project_id: str,
    record_type: str,
    field_name: str,
    field_type: str,
    required: bool = False,
    default_value: Optional[Any] = None,
    validation_rules: Optional[dict[str, Any]] = None,
    user_id: Optional[str] = None,
    sender_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Insert a governed project field definition and verify with read-back."""
    operation_id = str(uuid.uuid4())

    if not project_id:
        return {
            "success": False,
            "operation": "create_project_field",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": "project_id is required",
        }

    rec_type = (record_type or "").strip().lower()
    if rec_type not in ALLOWED_RECORD_TYPES:
        return {
            "success": False,
            "operation": "create_project_field",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": f"Invalid record_type '{record_type}'. Allowed: {ALLOWED_RECORD_TYPES}",
        }

    f_type = (field_type or "").strip().lower()
    if f_type not in ALLOWED_FIELD_TYPES:
        return {
            "success": False,
            "operation": "create_project_field",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": f"Invalid field_type '{field_type}'. Allowed: {ALLOWED_FIELD_TYPES}",
        }

    clean_field_name = (field_name or "").strip()
    if not clean_field_name:
        return {
            "success": False,
            "operation": "create_project_field",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": "field_name cannot be empty",
        }

    insert_sql = """
        INSERT INTO public.project_field_definitions (
            project_id, record_type, field_name, field_type, required, default_value, validation_rules, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, project_id, record_type, field_name, field_type, required, default_value, validation_rules, created_at;
    """
    params = (
        project_id,
        rec_type,
        clean_field_name,
        f_type,
        bool(required),
        json.dumps(default_value) if default_value is not None else None,
        json.dumps(validation_rules or {}),
        user_id,
    )

    try:
        rows = execute_query(insert_sql, params, user_id=user_id, sender_hash=sender_hash)
        if not rows:
            return {
                "success": False,
                "operation": "create_project_field",
                "operation_id": operation_id,
                "record_id": None,
                "affected_rows": 0,
                "data": {},
                "warnings": [],
                "error": "Insert into project_field_definitions returned 0 rows",
            }

        created = rows[0]
        record_id = str(created["id"])

        # Read-back verification
        verify_sql = "SELECT id, project_id, record_type, field_name, field_type FROM public.project_field_definitions WHERE id = %s;"
        verified_rows = execute_query(verify_sql, (record_id,), user_id=user_id, sender_hash=sender_hash)
        if not verified_rows:
            return {
                "success": False,
                "operation": "create_project_field",
                "operation_id": operation_id,
                "record_id": record_id,
                "affected_rows": 1,
                "data": created,
                "warnings": [],
                "error": "Read-back verification failed: record not found after insert",
            }

        return {
            "success": True,
            "operation": "create_project_field",
            "operation_id": operation_id,
            "record_id": record_id,
            "affected_rows": 1,
            "data": created,
            "warnings": [],
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "operation": "create_project_field",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": str(exc),
        }
