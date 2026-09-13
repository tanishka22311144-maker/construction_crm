from typing import Any, Optional
from services.database import execute_query


def read_project_data(
    project_id: str,
    record_type: Optional[str] = None,
    limit: int = 20,
    filters: Optional[dict[str, Any]] = None,
    user_id: Optional[str] = None,
) -> dict[str, Any]:
    """Read project records safely with server-side limit clamping and RLS."""
    if not project_id:
        return {
            "status": "error",
            "error": "project_id is required",
            "count": 0,
            "records": [],
        }

    # Strict server-side clamping to max 50 rows per .agents/rules/tools.md
    safe_limit = min(max(1, int(limit) if isinstance(limit, int) else 20), 50)

    query_parts = [
        "SELECT id, project_id, record_type, record_date, title, description, amount, unit, data, created_at, updated_at",
        "FROM public.project_records",
        "WHERE project_id = %s",
    ]
    params: list[Any] = [project_id]

    if record_type:
        query_parts.append("AND record_type = %s")
        params.append(record_type)

    query_parts.append("ORDER BY record_date DESC, created_at DESC")
    query_parts.append("LIMIT %s")
    params.append(safe_limit)

    full_query = " ".join(query_parts)

    try:
        rows = execute_query(
            full_query,
            tuple(params),
            user_id=user_id,
        )
        return {
            "status": "success",
            "project_id": project_id,
            "record_type": record_type,
            "count": len(rows),
            "records": rows,
        }
    except Exception as exc:
        return {
            "status": "error",
            "error": str(exc),
            "count": 0,
            "records": [],
        }
