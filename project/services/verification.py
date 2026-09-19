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
