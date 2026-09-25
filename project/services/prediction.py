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

    # 3. Determine actual progress entries by date
    # Check if records contain explicit progress indicators or compute cumulative progress
    date_to_progress: Dict[date, float] = {}
    max_record_date = start_date

    # Group daily logs / records
    for r in records:
        r_date = r.get("record_date")
        if not r_date:
            continue
        if isinstance(r_date, str):
            r_date = datetime.fromisoformat(r_date[:10]).date()
        if r_date > max_record_date:
            max_record_date = r_date

        data = r.get("data") or {}
        explicit_pct = None
        for key in ("progress", "progress_pct", "percentage", "completion"):
            if key in data:
                try:
                    explicit_pct = float(data[key])
                    break
                except (ValueError, TypeError):
                    pass

        if explicit_pct is not None:
            date_to_progress[r_date] = max(date_to_progress.get(r_date, 0.0), explicit_pct)

    # If no explicit progress percentages were provided in data JSON,
    # estimate actual cumulative progress based on recorded daily logs and milestone cadence
    current_progress = 0.0
    if date_to_progress:
        # Sort and take latest
        sorted_dates = sorted(date_to_progress.keys())
        current_progress = date_to_progress[sorted_dates[-1]]
    else:
        # Synthesize realistic progress from count of activities and elapsed time
        # E.g. each daily log represents work milestone, plus expense/equipment activity
        daily_log_count = sum(1 for r in records if r.get("record_type") == "daily_log")
        total_records_count = len(records)
        elapsed_days = max(1, (reference_date - start_date).days)
        
        # Base progress estimate: proportional to logged entries and elapsed timeline
        if total_records_count > 0:
            activity_weight = min(40.0, daily_log_count * 8.0 + total_records_count * 2.5)
            time_weight = min(60.0, (elapsed_days / target_duration_days) * 70.0)
            current_progress = round(min(100.0, activity_weight + time_weight), 1)
        else:
            current_progress = 0.0

    actual_as_of_date = max(start_date, min(reference_date, max_record_date))
    days_elapsed = max(1, (actual_as_of_date - start_date).days)

    # 4. Velocity and Predicted Completion Date
    # velocity = % work done per day
    actual_velocity = current_progress / days_elapsed
    expected_velocity = 100.0 / target_duration_days

    if actual_velocity > 0:
        remaining_pct = max(0.0, 100.0 - current_progress)
        days_to_finish = math.ceil(remaining_pct / actual_velocity)
        predicted_end_date = actual_as_of_date + timedelta(days=days_to_finish)
    else:
        # If no actual progress yet, prediction mirrors planned schedule
        predicted_end_date = planned_end_date

    # Max date to display on chart
    final_chart_date = max(planned_end_date, predicted_end_date)
    # Add a 5-day padding
    final_chart_date = final_chart_date + timedelta(days=5)

    # 5. Generate daily or sampled date timeline
    total_chart_days = (final_chart_date - start_date).days
    step_days = max(1, total_chart_days // 30)  # ~30 data points for smooth chart

    timeline_dates: List[date] = []
    curr = start_date
    while curr <= final_chart_date:
        timeline_dates.append(curr)
        curr += timedelta(days=step_days)
    if timeline_dates[-1] < final_chart_date:
        timeline_dates.append(final_chart_date)

    expected_curve: List[Optional[float]] = []
    actual_curve: List[Optional[float]] = []
    predicted_curve: List[Optional[float]] = []

    total_planned_days = (planned_end_date - start_date).days or 1

    for d in timeline_dates:
        # Expected work (S-curve up to planned_end_date, then 100%)
        if d <= start_date:
            exp_val = 0.0
        elif d >= planned_end_date:
            exp_val = 100.0
        else:
            t_ratio = (d - start_date).days / total_planned_days
            exp_val = _logistic_s_curve(t_ratio)
        expected_curve.append(exp_val)

        # Actual work (only plotted up to actual_as_of_date)
        if d <= actual_as_of_date:
            if d == start_date:
                act_val = 0.0
            elif d == actual_as_of_date:
                act_val = current_progress
            else:
                # Interpolate actual between start (0) and current_progress
                ratio = (d - start_date).days / days_elapsed
                # Slight realistic non-linearity
                act_val = round(current_progress * math.pow(ratio, 1.1), 1)
            actual_curve.append(act_val)
        else:
            actual_curve.append(None)

        # Predicted work (starts at actual_as_of_date and goes forward)
        if d < actual_as_of_date:
            predicted_curve.append(None)
        elif d == actual_as_of_date:
            predicted_curve.append(current_progress)
        elif d >= predicted_end_date:
            predicted_curve.append(100.0)
        else:
            pred_days = (predicted_end_date - actual_as_of_date).days or 1
            ratio = (d - actual_as_of_date).days / pred_days
            val = current_progress + (100.0 - current_progress) * ratio
            predicted_curve.append(round(min(100.0, val), 1))

    # Calculate status and variance
    t_ratio_today = min(1.0, max(0.0, (actual_as_of_date - start_date).days / total_planned_days))
    expected_today = _logistic_s_curve(t_ratio_today)
    variance_pct = round(current_progress - expected_today, 1)

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
