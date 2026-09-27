"""Work Prediction Service for Construction CRM.

Calculates:
1. Expected / Planned Work: Standard construction S-curve (logistic/sigmoid) baseline.
2. Actual Work Done: Cumulative progress derived from project_records up to today.
3. Predicted Work Forecast: Velocity-extrapolated forward trajectory predicting actual completion date.
"""
from datetime import date, datetime, timedelta
import math
from typing import Any, Dict, List, Optional

from services.database import execute_query


def _logistic_s_curve(t_ratio: float, k: float = 6.0) -> float:
    """Calculate standard construction S-curve progress percentage (0 to 100%).
    
    t_ratio: normalized time between 0.0 (project start) and 1.0 (planned end).
    Uses logistic sigmoid centered at 0.5.
    """
    if t_ratio <= 0.0:
        return 0.0
    if t_ratio >= 1.0:
        return 100.0
    # Sigmoid centered at 0.5 with steepness k
    raw = 1.0 / (1.0 + math.exp(-k * (t_ratio - 0.5)))
    # Normalize so f(0) = 0 and f(1) = 100
    f0 = 1.0 / (1.0 + math.exp(k * 0.5))
    f1 = 1.0 / (1.0 + math.exp(-k * 0.5))
    normalized = (raw - f0) / (f1 - f0) * 100.0
    return round(max(0.0, min(100.0, normalized)), 1)


def calculate_project_prediction(
    project_id: str,
    target_duration_days: int = 60,
    reference_date: Optional[date] = None,
) -> Dict[str, Any]:
    """Calculate work prediction curves and metrics for a project."""
    if reference_date is None:
        reference_date = date.today()

    # 1. Fetch project details
    proj_rows = execute_query(
        "SELECT id, project_name, project_code, location, status, created_at FROM public.projects WHERE id = %s",
        (project_id,),
    )
    if not proj_rows:
        raise ValueError(f"Project {project_id} not found")

    project = proj_rows[0]
    created_at = project["created_at"]
    if isinstance(created_at, datetime):
        start_date = created_at.date()
    elif isinstance(created_at, str):
        start_date = datetime.fromisoformat(created_at[:10]).date()
    else:
        start_date = reference_date - timedelta(days=14)

    # 2. Fetch project records
    records = execute_query(
        """
        SELECT id, record_type, record_date, title, amount, unit, data
        FROM public.project_records
        WHERE project_id = %s
        ORDER BY record_date ASC, created_at ASC
        """,
        (project_id,),
    )

    if records and records[0].get("record_date"):
        rec_start = records[0]["record_date"]
        if isinstance(rec_start, str):
            rec_start = datetime.fromisoformat(rec_start[:10]).date()
        if rec_start < start_date:
            start_date = rec_start

    planned_end_date = start_date + timedelta(days=target_duration_days)
    if planned_end_date <= start_date:
        planned_end_date = start_date + timedelta(days=30)

    # 3. Determine actual progress entries by date strictly based on daily_work_done sheet
    daily_work_records = [
        r for r in records if r.get("record_type") in ("daily_work_done", "daily_log")
    ]
    
    # Sort chronologically by record_date
    sorted_records = []
    for r in daily_work_records:
        r_date = r.get("record_date")
        if not r_date:
            continue
        if isinstance(r_date, str):
            try:
                r_date = datetime.fromisoformat(r_date[:10]).date()
            except ValueError:
                continue
        sorted_records.append((r_date, r))

    sorted_records.sort(key=lambda x: x[0])

    date_to_progress: Dict[date, float] = {}
    has_explicit = False

    for r_date, r in sorted_records:
        data = r.get("data") or {}
        explicit_pct = None
        for key in ("progress_pct", "progress_percentage", "progress", "percentage", "completion"):
            if key in data:
                try:
                    explicit_pct = float(data[key])
                    has_explicit = True
                    break
                except (ValueError, TypeError):
                    pass
        if explicit_pct is not None:
            date_to_progress[r_date] = max(date_to_progress.get(r_date, 0.0), explicit_pct)

    if not has_explicit and sorted_records:
        # Calculate milestone progress proportionally based on daily work entries
        total_items = len(sorted_records)
        date_counts: Dict[date, int] = {}
        for r_date, _ in sorted_records:
            date_counts[r_date] = date_counts.get(r_date, 0) + 1

        running = 0
        for r_date in sorted(date_counts.keys()):
            running += date_counts[r_date]
            pct = round((running / total_items) * 100.0, 1)
            date_to_progress[r_date] = pct

    # Timeline dates: project start date (0%) followed by each date recorded in daily_work_done
    recorded_dates = sorted(date_to_progress.keys())
    timeline_dates: List[date] = []
    actual_curve: List[Optional[float]] = []

    if recorded_dates:
        if recorded_dates[0] > start_date:
            timeline_dates.append(start_date)
            actual_curve.append(0.0)

        last_val = 0.0
        for d in recorded_dates:
            timeline_dates.append(d)
            val = max(last_val, date_to_progress[d])
            last_val = val
            actual_curve.append(val)
        current_progress = actual_curve[-1]
    else:
        timeline_dates = [start_date]
        actual_curve = [0.0]
        current_progress = 0.0

    actual_as_of_date = timeline_dates[-1]
    days_elapsed = max(1, (actual_as_of_date - start_date).days)
    actual_velocity = round(current_progress / days_elapsed, 2)
    expected_velocity = round(100.0 / target_duration_days, 2)

    total_planned_days = (planned_end_date - start_date).days or 1
    t_ratio_today = min(1.0, max(0.0, (actual_as_of_date - start_date).days / total_planned_days))
    expected_today = _logistic_s_curve(t_ratio_today)
    variance_pct = round(current_progress - expected_today, 1)

    if actual_velocity > 0 and current_progress < 100.0:
        days_remaining = int(math.ceil((100.0 - current_progress) / actual_velocity))
        predicted_end_date = actual_as_of_date + timedelta(days=days_remaining)
    elif current_progress >= 100.0:
        predicted_end_date = actual_as_of_date
    else:
        predicted_end_date = planned_end_date

    expected_curve: List[Optional[float]] = [None] * len(timeline_dates)
    predicted_curve: List[Optional[float]] = [None] * len(timeline_dates)

    if variance_pct >= 5.0:
        status_text = "Ahead of Schedule"
    elif variance_pct <= -5.0:
        status_text = "Behind Schedule"
    else:
        status_text = "On Track"

    return {
        "project_id": project_id,
        "project_name": project["project_name"],
        "project_code": project["project_code"],
        "location": project.get("location"),
        "status": project.get("status"),
        "dates": [d.isoformat() for d in timeline_dates],
        "expected_work": expected_curve,
        "actual_work": actual_curve,
        "predicted_work": predicted_curve,
        "metrics": {
            "start_date": start_date.isoformat(),
            "planned_completion_date": planned_end_date.isoformat(),
            "predicted_completion_date": predicted_end_date.isoformat(),
            "actual_as_of_date": actual_as_of_date.isoformat(),
            "current_progress_pct": current_progress,
            "expected_progress_pct": expected_today,
            "variance_pct": variance_pct,
            "schedule_status": status_text,
            "total_records": len(records),
            "velocity_pct_per_day": round(actual_velocity, 2),
        },
    }
