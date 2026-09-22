"""Durable audit events, agent runs, message deduplication, and chat persistence.

Per PROJECT_SPEC.md §10 (Idempotency), §12 (Memory), and §15 (Audit events).
"""
import json
import os
import uuid
from typing import Any, Optional

from services.database import execute_query, get_db_connection


# --- Webhook Deduplication (PROJECT_SPEC.md §10) ---

def check_and_start_message_dedup(message_id: str, sender_hash: str) -> dict[str, Any]:
    """Check processed_messages before graph execution.
    
    Returns:
    - {"is_duplicate": True, "status": "complete"|"processing", "run_id": ...}
    - {"is_duplicate": False, "status": "new"}
    """
    if not message_id:
        return {"is_duplicate": False, "status": "untracked"}

    check_sql = """
        SELECT status, run_id 
        FROM public.processed_messages 
        WHERE message_id = %s;
    """
    try:
        rows = execute_query(check_sql, (message_id,), sender_hash=sender_hash)
        if rows:
            existing = rows[0]
            status = existing.get("status")
            if status in ("complete", "processing"):
                return {
                    "is_duplicate": True,
                    "status": status,
                    "run_id": str(existing.get("run_id") or ""),
                }

        # Insert new processing record
        insert_sql = """
            INSERT INTO public.processed_messages (message_id, sender_hash, status)
            VALUES (%s, %s, 'processing')
            ON CONFLICT (message_id) DO UPDATE 
            SET status = 'processing', processed_at = now();
        """
        execute_query(insert_sql, (message_id, sender_hash), sender_hash=sender_hash)
        return {"is_duplicate": False, "status": "new"}
    except Exception as exc:  # pragma: no cover - fail-open for dedup to avoid blocking users
        print(json.dumps({"event": "dedup_check_error", "error": str(exc)}), flush=True)
        return {"is_duplicate": False, "status": "error_fallback"}


def complete_message_dedup(message_id: str, run_id: Optional[str] = None) -> None:
    """Mark a message_id as complete once reply is sent."""
    if not message_id:
        return
    sql = """
        UPDATE public.processed_messages
        SET status = 'complete', run_id = %s
        WHERE message_id = %s;
    """
    try:
        run_uuid = None
        if run_id:
            cleaned = run_id.replace("run-", "")
            if len(cleaned) == 12:
                # Pad to valid UUID if needed or try parse
                pass
            try:
                run_uuid = str(uuid.UUID(run_id))
            except ValueError:
                run_uuid = None
        execute_query(sql, (run_uuid, message_id))
    except Exception as exc:
        print(json.dumps({"event": "dedup_complete_error", "error": str(exc)}), flush=True)


# --- Durable Agent Runs & Audit Events (PROJECT_SPEC.md §15) ---

def record_agent_run(
    run_id: str,
    thread_id: str,
    user_id: Optional[str],
    message_id: str,
    intent: Optional[str] = None,
    current_node: Optional[str] = None,
    status: str = "running",
    sender_hash: Optional[str] = None,
) -> None:
    """Ensure agent_runs row exists for foreign key references."""
    if not run_id:
        return
    try:
        run_uuid = str(uuid.UUID(run_id))
    except (ValueError, TypeError):
        return

    sql = """
        INSERT INTO public.agent_runs (id, thread_id, user_id, message_id, status, intent, current_node)
        VALUES (%s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (id) DO UPDATE
        SET status = EXCLUDED.status,
            current_node = EXCLUDED.current_node,
            intent = COALESCE(EXCLUDED.intent, agent_runs.intent);
    """
    try:
        user_uuid = None
        if user_id:
            try:
                user_uuid = str(uuid.UUID(user_id))
            except ValueError:
                user_uuid = None
        execute_query(
            sql,
            (run_uuid, thread_id or "", user_uuid, message_id or "", status, intent, current_node),
            sender_hash=sender_hash,
            user_id=user_id,
        )
    except Exception as exc:
        print(json.dumps({"event": "record_agent_run_error", "error": str(exc)}), flush=True)


def record_agent_event(
    run_id: str,
    sequence_number: int,
    event_type: str,
    status: Optional[str] = None,
    node_name: Optional[str] = None,
    tool_name: Optional[str] = None,
    input_json: Optional[dict] = None,
    output_json: Optional[dict] = None,
    decision_json: Optional[dict] = None,
    error_json: Optional[dict] = None,
    duration_ms: Optional[int] = None,
    user_id: Optional[str] = None,
    sender_hash: Optional[str] = None,
) -> None:
    """Append durable audit event to public.agent_events table."""
    if not run_id:
        return
    try:
        run_uuid = str(uuid.UUID(run_id))
    except (ValueError, TypeError):
        return

    sql = """
        INSERT INTO public.agent_events (
            run_id, sequence_number, event_type, status, node_name,
            tool_name, input_json, output_json, decision_json, error_json, duration_ms
        )
        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        ON CONFLICT (run_id, sequence_number) DO NOTHING;
    """
    try:
        execute_query(
            sql,
            (
                run_uuid,
                sequence_number,
                event_type,
                status,
                node_name,
                tool_name,
                json.dumps(input_json, default=str) if input_json is not None else None,
                json.dumps(output_json, default=str) if output_json is not None else None,
                json.dumps(decision_json, default=str) if decision_json is not None else None,
                json.dumps(error_json, default=str) if error_json is not None else None,
                duration_ms,
            ),
            sender_hash=sender_hash,
            user_id=user_id,
        )
    except Exception as exc:
        print(json.dumps({"event": "record_agent_event_error", "error": str(exc)}), flush=True)


def check_write_idempotency(
    idempotency_key: str,
    project_id: str,
    user_id: Optional[str] = None,
) -> Optional[dict[str, Any]]:
    """Check if a project record with this idempotency key was already created."""
    if not idempotency_key or not project_id:
        return None

    sql = """
        SELECT id, project_id, record_type, record_date, title, description, amount, unit, data, created_at
        FROM public.project_records
        WHERE project_id = %s
          AND data->>'idempotency_key' = %s
        LIMIT 1;
    """
    try:
        rows = execute_query(sql, (project_id, idempotency_key), user_id=user_id)
        if rows:
            return rows[0]
        return None
    except Exception as exc:
        print(json.dumps({"event": "check_write_idempotency_error", "error": str(exc)}), flush=True)
        return None


def record_chat_session(
    user_id: Optional[str],
    user_message: str,
    assistant_reply: str,
    run_id: Optional[str] = None,
    sender_hash: Optional[str] = None,
) -> None:
    """Persist conversation exchange to chat_sessions table for multi-turn memory."""
    if not user_id:
        return

    sql = """
        INSERT INTO public.chat_sessions (user_id, user_message, assistant_reply, run_id)
        VALUES (%s, %s, %s, %s);
    """
    try:
        run_uuid = None
        if run_id:
            try:
                run_uuid = str(uuid.UUID(run_id))
            except ValueError:
                run_uuid = None

        execute_query(
            sql,
            (user_id, user_message, assistant_reply, run_uuid),
            sender_hash=sender_hash,
            user_id=user_id,
        )
    except Exception as exc:
        print(json.dumps({"event": "record_chat_session_error", "error": str(exc)}), flush=True)


def load_recent_chat_history(
    user_id: Optional[str],
    sender_hash: Optional[str] = None,
    limit: int = 6,
    inactivity_cutoff_hours: Optional[float] = None,
) -> list[dict[str, str]]:
    """Retrieve last N messages from chat_sessions to supply multi-turn context within an inactivity cutoff.

    Defaults to 2.0 hours (configurable via CHAT_SESSION_INACTIVITY_HOURS env var or direct arg).
    Set inactivity_cutoff_hours <= 0 to disable cutoff and fetch purely by limit.
    """
    if not user_id:
        return []

    if inactivity_cutoff_hours is None:
        try:
            inactivity_cutoff_hours = float(os.getenv("CHAT_SESSION_INACTIVITY_HOURS", "2"))
        except ValueError:
            inactivity_cutoff_hours = 2.0

    if inactivity_cutoff_hours > 0:
        sql = """
            SELECT user_message, assistant_reply, created_at
            FROM public.chat_sessions
            WHERE user_id = %s
              AND created_at >= NOW() - (%s * INTERVAL '1 hour')
            ORDER BY created_at DESC
            LIMIT %s;
        """
        params: tuple = (user_id, inactivity_cutoff_hours, limit)
    else:
        sql = """
            SELECT user_message, assistant_reply, created_at
            FROM public.chat_sessions
            WHERE user_id = %s
            ORDER BY created_at DESC
            LIMIT %s;
        """
        params = (user_id, limit)

    try:
        rows = execute_query(sql, params, sender_hash=sender_hash, user_id=user_id)
        # Reverse to chronological order
        chronological = list(reversed(rows))
        return [
            {
                "user_message": r["user_message"],
                "assistant_reply": r["assistant_reply"],
            }
            for r in chronological
        ]
    except Exception as exc:
        print(json.dumps({"event": "load_chat_history_error", "error": str(exc)}), flush=True)
        return []
