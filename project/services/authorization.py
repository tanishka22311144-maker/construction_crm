from typing import Any, Optional
from services.database import execute_query


def check_user_project_read_access(user_id: str, project_id: str) -> bool:
    """Check if the given user has can_read permission on the project."""
    if not user_id or not project_id:
        return False

    query = """
        SELECT can_read
        FROM public.user_project_access
        WHERE user_id = %s AND project_id = %s
        LIMIT 1
    """
    try:
        rows = execute_query(query, (user_id, project_id), user_id=user_id)
        if rows and rows[0].get("can_read"):
            return True
        return False
    except Exception:
        # Fail closed on any database/query error
        return False


def authorize(
    user_id: Optional[str],
    project_id: Optional[str],
    operation: str = "read_project_data",
    **kwargs: Any,
) -> dict:
    """Deterministic authorization gate for project operations.

    For Stage 2, handles read authorization via user_project_access.can_read.
    Write and approval permissions will be added in Stage 5 and Stage 6.
    """
    if not user_id:
        return {
            "allowed": False,
            "reason": "Unauthenticated or unresolvable sender identity",
            "risk_level": "none",
            "human_approval_required": False,
        }

    if not project_id:
        return {
            "allowed": False,
            "reason": "Project context missing or unresolved",
            "risk_level": "none",
            "human_approval_required": False,
        }

    if operation in ("read", "read_project_data"):
        has_access = check_user_project_read_access(user_id, project_id)
        if has_access:
            return {
                "allowed": True,
                "reason": "Read access granted",
                "risk_level": "low",
                "human_approval_required": False,
            }
        return {
            "allowed": False,
            "reason": "User does not have read access to this project",
            "risk_level": "none",
            "human_approval_required": False,
        }

    # Any other operation is not yet supported in Stage 2
    return {
        "allowed": False,
        "reason": f"Operation '{operation}' is not supported in current stage",
        "risk_level": "high",
        "human_approval_required": True,
    }
