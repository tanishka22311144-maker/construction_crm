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


def check_user_project_write_access(user_id: str, project_id: str) -> bool:
    """Check if the given user has can_add_rows permission on the project."""
    if not user_id or not project_id:
        return False

    query = """
        SELECT can_add_rows
        FROM public.user_project_access
        WHERE user_id = %s AND project_id = %s
        LIMIT 1
    """
    try:
        rows = execute_query(query, (user_id, project_id), user_id=user_id)
        if rows and rows[0].get("can_add_rows"):
            return True
        return False
    except Exception:
        # Fail closed on any database/query error
        return False


def check_user_project_field_access(user_id: str, project_id: str) -> bool:
    """Check if user can propose or manage fields on the project."""
    if not user_id or not project_id:
        return False
    sql_role = "SELECT role FROM public.agent_users WHERE id = %s AND is_active = true"
    try:
        u_rows = execute_query(sql_role, (user_id,), user_id=user_id)
        if u_rows and u_rows[0].get("role") in ("project_admin", "system_admin"):
            return True
    except Exception:
        pass

    sql = """
        SELECT can_propose_fields, can_approve_fields
        FROM public.user_project_access
        WHERE user_id = %s AND project_id = %s
        LIMIT 1;
    """
    try:
        rows = execute_query(sql, (user_id, project_id), user_id=user_id)
        if rows and (rows[0].get("can_propose_fields") or rows[0].get("can_approve_fields")):
            return True
        return False
    except Exception:
        return False


def check_user_project_creation_access(user_id: str) -> bool:
    """Check if user has permission to propose or create a new project."""
    if not user_id:
        return False
    sql_role = "SELECT role FROM public.agent_users WHERE id = %s AND is_active = true"
    try:
        u_rows = execute_query(sql_role, (user_id,), user_id=user_id)
        if u_rows and u_rows[0].get("role") in ("project_admin", "system_admin"):
            return True
    except Exception:
        pass

    sql = """
        SELECT can_propose_projects, can_approve_projects
        FROM public.user_project_access
        WHERE user_id = %s
        LIMIT 1;
    """
    try:
        rows = execute_query(sql, (user_id,), user_id=user_id)
        if rows and (rows[0].get("can_propose_projects") or rows[0].get("can_approve_projects")):
            return True
        return False
    except Exception:
        return False


def classify_risk(
    operation: str,
    tool_arguments: Optional[dict[str, Any]] = None,
    user_role: Optional[str] = None,
) -> dict[str, Any]:
    """Classify risk per PROJECT_SPEC.md §6 and determine approval requirement."""
    import os
    expense_threshold = float(os.getenv("EXPENSE_APPROVAL_THRESHOLD", "50000"))
    args = tool_arguments or {}
    op = (operation or "").strip().lower()

    if op in ("read", "read_project_data"):
        return {
            "risk_level": "low",
            "human_approval_required": False,
            "required_role": None,
        }

    if op in ("write", "add_project_row"):
        rec_type = args.get("record_type")
        amt = args.get("amount")
        try:
            amt_num = float(amt) if amt is not None else 0.0
        except (ValueError, TypeError):
            amt_num = 0.0

        if rec_type == "expense" and amt_num > expense_threshold:
            return {
                "risk_level": "high",
                "human_approval_required": True,
                "required_role": "finance_approver",
                "threshold_exceeded": True,
            }

        return {
            "risk_level": "medium",
            "human_approval_required": False,
            "required_role": None,
        }

    if op in ("create_project_field", "propose_field"):
        return {
            "risk_level": "high",
            "human_approval_required": True,
            "required_role": "project_admin",
        }

    if op in ("create_project", "propose_project"):
        return {
            "risk_level": "critical",
            "human_approval_required": True,
            "required_role": "system_admin",
        }

    return {
        "risk_level": "high",
        "human_approval_required": True,
        "required_role": "system_admin",
    }


def authorize(
    user_id: Optional[str],
    project_id: Optional[str],
    operation: str = "read_project_data",
    **kwargs: Any,
) -> dict:
    """Deterministic authorization gate for project operations (Stage 6).

    Handles read, write, create_project_field, and create_project operations.
    """
    if not user_id:
        return {
            "allowed": False,
            "reason": "Unauthenticated or unresolvable sender identity",
            "risk_level": "none",
            "human_approval_required": False,
            "required_role": None,
        }

    tool_args = kwargs.get("tool_arguments") or {}
    risk_info = classify_risk(operation, tool_arguments=tool_args)

    if operation in ("read", "read_project_data"):
        if not project_id:
            return {
                "allowed": False,
                "reason": "Project context missing or unresolved",
                "risk_level": "none",
                "human_approval_required": False,
                "required_role": None,
            }
        has_access = check_user_project_read_access(user_id, project_id)
        if has_access:
            return {
                "allowed": True,
                "reason": "Read access granted",
                "risk_level": "low",
                "human_approval_required": False,
                "required_role": None,
            }
        return {
            "allowed": False,
            "reason": "User does not have read access to this project",
            "risk_level": "none",
            "human_approval_required": False,
            "required_role": None,
        }

    if operation in ("write", "add_project_row"):
        if not project_id:
            return {
                "allowed": False,
                "reason": "Project context missing or unresolved",
                "risk_level": "none",
                "human_approval_required": False,
                "required_role": None,
            }
        has_write_access = check_user_project_write_access(user_id, project_id)
        if has_write_access:
            return {
                "allowed": True,
                "reason": "Write access granted",
                "risk_level": risk_info["risk_level"],
                "human_approval_required": risk_info["human_approval_required"],
                "required_role": risk_info.get("required_role"),
            }
        return {
            "allowed": False,
            "reason": "User does not have permission to add records to this project",
            "risk_level": "none",
            "human_approval_required": False,
            "required_role": None,
        }

    if operation == "create_project_field":
        if not project_id:
            return {
                "allowed": False,
                "reason": "Project context missing or unresolved",
                "risk_level": "none",
                "human_approval_required": False,
                "required_role": None,
            }
        has_field_access = check_user_project_field_access(user_id, project_id)
        if has_field_access:
            return {
                "allowed": True,
                "reason": "Field creation permitted pending approval",
                "risk_level": risk_info["risk_level"],
                "human_approval_required": risk_info["human_approval_required"],
                "required_role": risk_info.get("required_role"),
            }
        return {
            "allowed": False,
            "reason": "User does not have permission to propose fields for this project",
            "risk_level": "none",
            "human_approval_required": False,
            "required_role": None,
        }

    if operation == "create_project":
        has_create_access = check_user_project_creation_access(user_id)
        if has_create_access:
            return {
                "allowed": True,
                "reason": "Project creation permitted pending approval",
                "risk_level": risk_info["risk_level"],
                "human_approval_required": risk_info["human_approval_required"],
                "required_role": risk_info.get("required_role"),
            }
        return {
            "allowed": False,
            "reason": "User does not have permission to propose new projects",
            "risk_level": "none",
            "human_approval_required": False,
            "required_role": None,
        }

    return {
        "allowed": False,
        "reason": f"Operation '{operation}' is not supported",
        "risk_level": "high",
        "human_approval_required": False,
        "required_role": None,
    }
