"""Tool: create_project for atomic project onboarding.

Per PROJECT_SPEC.md §6 Tool 4:
Atomically creates project row, default field definitions, and creator access.
"""
from typing import Any, Optional
import uuid

from services.database import get_db_connection, bind_request_context


def create_project(
    project_name: str,
    project_code: str,
    location: Optional[str] = None,
    status: str = "active",
    user_id: Optional[str] = None,
    sender_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Atomically create a project, default fields, and creator access."""
    operation_id = str(uuid.uuid4())

    name = (project_name or "").strip()
    code = (project_code or "").strip().upper()

    if not name or not code:
        return {
            "success": False,
            "operation": "create_project",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": "project_name and project_code are both required",
        }

    try:
        with get_db_connection() as conn:
            bind_request_context(conn, sender_hash=sender_hash, user_id=user_id)
            with conn.cursor() as cur:
                # 1. Insert Project
                cur.execute(
                    """
                    INSERT INTO public.projects (project_name, project_code, location, status, created_by)
                    VALUES (%s, %s, %s, %s, %s)
                    RETURNING id, project_name, project_code, location, status, created_at;
                    """,
                    (name, code, location, status, user_id),
                )
                project_row = cur.fetchone()
                project_id = str(project_row["id"])

                # 2. Insert Default Project Field Definitions
                default_fields = [
                    (project_id, "expense", "category", "text", True, "{}"),
                    (project_id, "expense", "payment_mode", "text", False, "{}"),
                    (project_id, "daily_log", "weather", "text", False, "{}"),
                    (project_id, "daily_log", "workers_count", "integer", False, "{}"),
                    (project_id, "equipment_log", "equipment_name", "text", True, "{}"),
                    (project_id, "equipment_log", "hours_operated", "numeric", False, "{}"),
                ]
                for p_id, rec_type, f_name, f_type, req, v_rules in default_fields:
                    cur.execute(
                        """
                        INSERT INTO public.project_field_definitions (
                            project_id, record_type, field_name, field_type, required, validation_rules, created_by
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT DO NOTHING;
                        """,
                        (p_id, rec_type, f_name, f_type, req, v_rules, user_id),
                    )

                # 3. Grant Creator Access if user_id is provided
                if user_id:
                    cur.execute(
                        """
                        INSERT INTO public.user_project_access (
                            user_id, project_id, can_read, can_add_rows, can_propose_fields,
                            can_approve_fields, can_propose_projects, can_approve_projects
                        )
                        VALUES (%s, %s, true, true, true, true, true, true)
                        ON CONFLICT DO NOTHING;
                        """,
                        (user_id, project_id),
                    )

            conn.commit()

        return {
            "success": True,
            "operation": "create_project",
            "operation_id": operation_id,
            "record_id": project_id,
            "affected_rows": 1,
            "data": dict(project_row),
            "warnings": [],
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "operation": "create_project",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": str(exc),
        }
