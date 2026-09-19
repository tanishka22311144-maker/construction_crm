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
