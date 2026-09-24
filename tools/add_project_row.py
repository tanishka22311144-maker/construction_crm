"""Write tool: add_project_row for recording construction site data.

Implements strict result envelope per .agents/skills/verification-envelope/SKILL.md
and idempotency check per .agents/skills/idempotency-key/SKILL.md.
"""
from datetime import datetime, timezone
import hashlib
import json
from typing import Any, Optional
import uuid

from services.audit import check_write_idempotency
from services.database import execute_query


ALLOWED_RECORD_TYPES = {"daily_log", "expense", "equipment_log"}


def add_project_row(
    project_id: str,
    record_type: str,
    record_date: Optional[str] = None,
    title: Optional[str] = None,
    description: Optional[str] = None,
    amount: Optional[float] = None,
    unit: Optional[str] = "INR",
    data: Optional[dict[str, Any]] = None,
    message_id: Optional[str] = None,
    user_id: Optional[str] = None,
    sender_hash: Optional[str] = None,
) -> dict[str, Any]:
    """Insert one project record with write idempotency and strict result envelope."""
    operation_id = str(uuid.uuid4())

    if not project_id:
        return {
            "success": False,
            "operation": "add_project_row",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": "project_id is required",
        }

    # Normalize record_type
    rec_type = (record_type or "").strip().lower()
    if rec_type not in ALLOWED_RECORD_TYPES:
        return {
            "success": False,
            "operation": "add_project_row",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": f"Invalid record_type '{record_type}'. Allowed types: {', '.join(sorted(ALLOWED_RECORD_TYPES))}",
        }

    # Clean amount if supplied
    parsed_amount = None
    if amount is not None:
        try:
            parsed_amount = float(amount)
        except (ValueError, TypeError):
            return {
                "success": False,
                "operation": "add_project_row",
                "operation_id": operation_id,
                "record_id": None,
                "affected_rows": 0,
                "data": {},
                "warnings": [],
                "error": f"Invalid amount '{amount}': must be a valid number",
            }

    # Date defaults to today in UTC
    final_date = record_date or datetime.now(timezone.utc).date().isoformat()
    record_data = dict(data) if isinstance(data, dict) else {}

    # Compute idempotency key (PROJECT_SPEC.md §10)
    # Keyed on canonical write arguments only — NOT on message_id — so that
    # two different WhatsApp messages with identical content are caught as
    # duplicates within the time window enforced by check_write_idempotency.
    # message_id-level dedup is handled earlier at the webhook layer
    # (check_and_start_message_dedup in api/index.py).
    idempotency_payload = {
        "project_id": str(project_id),
        "record_type": rec_type,
        "title": title or "",
        "amount": parsed_amount,
        "unit": unit or "INR",
    }
    canonical_args = json.dumps(idempotency_payload, sort_keys=True)
    idempotency_key = hashlib.sha256(
        f"add_project_row:{canonical_args}".encode("utf-8")
    ).hexdigest()

    # Check for existing insert before writing
    existing_record = check_write_idempotency(idempotency_key, project_id, user_id=user_id)
    if existing_record:
        return {
            "success": True,
            "operation": "add_project_row",
            "operation_id": operation_id,
            "record_id": str(existing_record["id"]),
            "affected_rows": 1,
            "data": existing_record,
            "warnings": ["Record already existed (idempotency match)"],
            "error": None,
            "idempotent_replay": True,
        }

    # Store idempotency key inside JSONB data
    record_data["idempotency_key"] = idempotency_key

    insert_sql = """
        INSERT INTO public.project_records (
            project_id, record_type, record_date, title, description, amount, unit, data, created_by
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
        RETURNING id, project_id, record_type, record_date, title, description, amount, unit, data, created_at;
    """
    params = (
        project_id,
        rec_type,
        final_date,
        title,
        description,
        parsed_amount,
        unit,
        json.dumps(record_data),
        user_id,
    )

    try:
        rows = execute_query(
            insert_sql,
            params,
            user_id=user_id,
            sender_hash=sender_hash,
        )
        if not rows:
            return {
                "success": False,
                "operation": "add_project_row",
                "operation_id": operation_id,
                "record_id": None,
                "affected_rows": 0,
                "data": {},
                "warnings": [],
                "error": "Insert returned 0 rows",
            }

        created_row = rows[0]
        return {
            "success": True,
            "operation": "add_project_row",
            "operation_id": operation_id,
            "record_id": str(created_row["id"]),
            "affected_rows": 1,
            "data": created_row,
            "warnings": [],
            "error": None,
        }
    except Exception as exc:
        return {
            "success": False,
            "operation": "add_project_row",
            "operation_id": operation_id,
            "record_id": None,
            "affected_rows": 0,
            "data": {},
            "warnings": [],
            "error": str(exc),
        }
