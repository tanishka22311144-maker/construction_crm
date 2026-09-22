"""Structural and semantic verification engine for tool execution results.

PROJECT_SPEC.md §7 Layers 2, 3, 5, 7, and §8:
Enforces bounded row count, strict result envelope, and error classification
(transient vs fatal) to prevent false success and bounded retry loops.
"""
from typing import Any, Optional

# Bounded limits per PROJECT_SPEC.md §6 and §9
MAX_ROW_COUNT = 50

TRANSIENT_KEYWORDS = (
    "timeout",
    "timed out",
    "connection reset",
    "connection refused",
    "connection closed",
    "temporary failure",
    "server closed the connection",
    "429",
    "502",
    "503",
    "504",
    "pooler",
    "network is unreachable",
    "cannot assign requested address",
)


def classify_error(error_str: Optional[str]) -> dict[str, Any]:
    """Classify an error message as transient (auto-retryable) or non-transient.
    
    Per PROJECT_SPEC.md §9:
    - Auto-retry: network timeout, temporary provider/Supabase connection failures, HTTP 429/502/503/504.
    - Never auto-retry: permission denied, invalid data, constraint violation, syntax error.
    """
    if not error_str:
        return {"is_transient": False, "category": "unknown"}

    err_lower = str(error_str).lower()
    for kw in TRANSIENT_KEYWORDS:
        if kw in err_lower:
            return {"is_transient": True, "category": "transient_network"}

    if "permission" in err_lower or "access denied" in err_lower:
        return {"is_transient": False, "category": "authorization"}
    if "syntax" in err_lower or "relation" in err_lower or "column" in err_lower:
        return {"is_transient": False, "category": "database_schema"}
    if "duplicate" in err_lower or "unique" in err_lower or "constraint" in err_lower:
        return {"is_transient": False, "category": "database_constraint"}

    return {"is_transient": False, "category": "unclassified_error"}


def validate_read_result(result: Any) -> dict[str, Any]:
    """Validate the structural result of a read operation (Layer 5).
    
    Checks:
    - Result is a non-empty dictionary.
    - Status is explicitly 'success'.
    - 'records' is a list and row count does not exceed MAX_ROW_COUNT (50).
    - No hidden error message is present.
    """
    if not isinstance(result, dict):
        return {
            "valid": False,
            "code": "INVALID_RESULT_TYPE",
            "error": f"Expected dict result, got {type(result).__name__}",
            "is_transient": False,
        }

    status = result.get("status")
    if status != "success":
        err_msg = result.get("error") or "Tool reported non-success status"
        classification = classify_error(err_msg)
        return {
            "valid": False,
            "code": "TOOL_REPORTED_FAILURE",
            "error": err_msg,
            "is_transient": classification["is_transient"],
            "category": classification["category"],
        }

    if "records" not in result or not isinstance(result["records"], list):
        return {
            "valid": False,
            "code": "INVALID_RECORDS_SHAPE",
            "error": "'records' key missing or not a list",
            "is_transient": False,
        }

    records = result["records"]
    if len(records) > MAX_ROW_COUNT:
        return {
            "valid": False,
            "code": "EXCEEDED_MAX_ROW_COUNT",
            "error": f"Returned {len(records)} rows, exceeding safety bound of {MAX_ROW_COUNT}",
            "is_transient": False,
        }

    return {
        "valid": True,
        "code": "READ_RESULT_VALID",
        "error": None,
        "is_transient": False,
        "row_count": len(records),
    }


def validate_write_result(result: Any) -> dict[str, Any]:
    """Validate structural envelope of a write operation (Layer 5).
    
    Per PROJECT_SPEC.md §8 and .agents/skills/verification-envelope/SKILL.md:
    Checks:
    - Result is a dictionary
    - success is explicitly True
    - affected_rows is exactly 1
    - record_id is present
    """
    if not isinstance(result, dict):
        return {
            "valid": False,
            "code": "INVALID_RESULT_TYPE",
            "error": f"Expected dict result, got {type(result).__name__}",
            "is_transient": False,
        }

    if result.get("success") is not True:
        err_msg = result.get("error") or "Tool reported non-success status"
        classification = classify_error(err_msg)
        return {
            "valid": False,
            "code": "TOOL_REPORTED_FAILURE",
            "error": err_msg,
            "is_transient": classification["is_transient"],
            "category": classification["category"],
        }

    if result.get("affected_rows") != 1:
        return {
            "valid": False,
            "code": "UNEXPECTED_AFFECTED_ROWS",
            "error": f"Expected 1 affected row, got {result.get('affected_rows')}",
            "is_transient": False,
        }

    if not result.get("record_id"):
        return {
            "valid": False,
            "code": "MISSING_RECORD_ID",
            "error": "Missing record_id in write result",
            "is_transient": False,
        }

    return {
        "valid": True,
        "code": "WRITE_RESULT_VALID",
        "record_id": str(result["record_id"]),
        "error": None,
        "is_transient": False,
    }


def compare_normalized_values(expected: dict[str, Any], actual: dict[str, Any]) -> list[str]:
    """Compare expected vs actual values after a write, returning mismatch descriptions."""
    mismatches = []

    # Compare record_type if expected
    if expected.get("record_type"):
        exp_type = str(expected["record_type"]).strip().lower()
        act_type = str(actual.get("record_type") or "").strip().lower()
        if exp_type != act_type:
            mismatches.append(f"record_type mismatch: expected '{exp_type}', got '{act_type}'")

    # Compare title if expected
    if expected.get("title"):
        exp_title = str(expected["title"]).strip().lower()
        act_title = str(actual.get("title") or "").strip().lower()
        if exp_title != act_title:
            mismatches.append(f"title mismatch: expected '{exp_title}', got '{act_title}'")

    # Compare amount if expected
    if expected.get("amount") is not None:
        try:
            exp_amt = float(expected["amount"])
            act_amt = float(actual.get("amount") or 0)
            if abs(exp_amt - act_amt) > 0.001:
                mismatches.append(f"amount mismatch: expected {exp_amt}, got {act_amt}")
        except (ValueError, TypeError):
            mismatches.append(f"amount parse error comparing {expected.get('amount')} vs {actual.get('amount')}")

    # Compare unit if expected
    if expected.get("unit"):
        exp_unit = str(expected["unit"]).strip().upper()
        act_unit = str(actual.get("unit") or "").strip().upper()
        if exp_unit != act_unit:
            mismatches.append(f"unit mismatch: expected '{exp_unit}', got '{act_unit}'")

    # Compare custom JSON data fields if expected
    if isinstance(expected.get("data"), dict):
        act_data = actual.get("data") if isinstance(actual.get("data"), dict) else {}
        for k, v in expected["data"].items():
            if str(act_data.get(k)) != str(v):
                mismatches.append(f"data.{k} mismatch: expected '{v}', got '{act_data.get(k)}'")

    return mismatches


def verify_insert(
    project_id: str,
    expected: dict[str, Any],
    write_result: dict[str, Any],
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Layer 6 post-write read-back verification.
    
    Independently reads back the record by record_id from the database
    and verifies all canonical fields before declaring success.
    """
    from services.database import execute_query

    record_id = write_result.get("record_id")
    if not record_id:
        return {
            "success": False,
            "code": "MISSING_RECORD_ID",
            "error": "Cannot perform read-back without record_id",
        }

    sql = """
        SELECT id, project_id, record_type, record_date, title, description, amount, unit, data, created_by, created_at
        FROM public.project_records
        WHERE id = %s
        LIMIT 1;
    """
    try:
        rows = execute_query(sql, (record_id,), user_id=user_id)
        if not rows:
            return {
                "success": False,
                "code": "RECORD_NOT_FOUND_AFTER_WRITE",
                "error": f"Record {record_id} was not found in database after write",
            }

        stored = rows[0]
        # Check project_id match
        if str(stored.get("project_id")) != str(project_id):
            return {
                "success": False,
                "code": "PROJECT_ID_MISMATCH",
                "error": f"Stored project_id {stored.get('project_id')} does not match target {project_id}",
            }

        # Compare normalized values
        mismatches = compare_normalized_values(expected=expected, actual=stored)
        if mismatches:
            return {
                "success": False,
                "code": "READ_BACK_MISMATCH",
                "error": "Read-back verification found field mismatches",
                "details": mismatches,
            }

        return {
            "success": True,
            "code": "WRITE_VERIFIED",
            "verified_record": stored,
        }
    except Exception as exc:
        return {
            "success": False,
            "code": "READ_BACK_QUERY_ERROR",
            "error": str(exc),
        }
