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


def sanitize_db_url(raw_url: str) -> str:
    """Ensure the password component of a Postgres URL is URL‑encoded.

    This handles cases where the password itself contains an '@' which would
    otherwise be interpreted as the host delimiter, leading to a host‑name
    resolution error.
    """
    from urllib.parse import urlparse, urlunparse, quote
    parsed = urlparse(raw_url)
    if parsed.password and "@" in parsed.password:
        encoded_pwd = quote(parsed.password, safe="")
        # rebuild netloc with possible username and encoded password
        netloc = ""
        if parsed.username:
            netloc += f"{parsed.username}:{encoded_pwd}@"
        else:
            netloc += f"{encoded_pwd}@"
        netloc += parsed.hostname or ""
        if parsed.port:
            netloc += f":{parsed.port}"
        parsed = parsed._replace(netloc=netloc)
        return urlunparse(parsed)
    return raw_url
def get_database_url() -> str:
    """Return the Postgres connection URL.

    Preference order:
    1. SUPABASE_DB_URL – Supabase provides this for the Postgres instance.
    2. DATABASE_URL – legacy fallback.
    """
    return os.getenv("SUPABASE_DB_URL") or os.getenv("DATABASE_URL") or ""



@contextlib.contextmanager
def get_db_connection(
    sender_hash: Optional[str] = None,
    user_id: Optional[str] = None,
) -> Generator[Any, None, None]:
    """Context manager for obtaining a database connection with bound request context."""
    db_url = sanitize_db_url(get_database_url())
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
