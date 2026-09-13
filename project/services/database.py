import contextlib
import os
from typing import Any, Generator, Optional

try:
    import psycopg2
    from psycopg2.extras import RealDictCursor
except ImportError:  # pragma: no cover
    psycopg2 = None
    RealDictCursor = None


def bind_request_context(conn: Any, sender_hash: Optional[str] = None, user_id: Optional[str] = None) -> None:
    """Set Postgres session variables scoped to current transaction for RLS.

    Uses is_local=True (via set_config(..., true)) so that session variables
    do not leak across pooled connections.
    """
    with conn.cursor() as cur:
        cur.execute(
            "SELECT set_config('app.current_sender_hash', %s, true)",
            (sender_hash or "",),
        )
        cur.execute(
            "SELECT set_config('app.current_user_id', %s, true)",
            (user_id or "",),
        )


def get_database_url() -> str:
    return (
        os.getenv("DATABASE_URL")
        or os.getenv("SUPABASE_DB_URL")
        or os.getenv("POSTGRES_URL")
        or ""
    )


@contextlib.contextmanager
def get_db_connection(
    sender_hash: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Generator[Any, None, None]:
    """Context manager for obtaining a database connection with bound request context."""
    db_url = get_database_url()
    if not db_url or psycopg2 is None:
        raise RuntimeError("Database connection not configured or psycopg2 is unavailable.")

    conn = psycopg2.connect(db_url, cursor_factory=RealDictCursor)
    try:
        bind_request_context(conn, sender_hash=sender_hash, user_id=user_id)
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def execute_query(
    query: str,
    params: Optional[tuple | dict] = None,
    sender_hash: Optional[str] = None,
    user_id: Optional[str] = None,
) -> list[dict]:
    """Execute a read query within bound request context and return rows as list of dicts."""
    with get_db_connection(sender_hash=sender_hash, user_id=user_id) as conn:
        with conn.cursor() as cur:
            cur.execute(query, params or ())
            if cur.description:
                rows = cur.fetchall()
                return [dict(row) for row in rows]
            return []
