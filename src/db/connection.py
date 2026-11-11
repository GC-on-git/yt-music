"""SQLite connection helpers with parameterized queries and transactions."""

from __future__ import annotations

import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable, Iterator, Sequence, TypeVar

from src.config import get_settings

# Streamlit UI and background jobs share one DB file. Wait for writers instead of
# failing immediately with "database is locked".
BUSY_TIMEOUT_MS = 60_000
CONNECT_TIMEOUT_S = 60.0

T = TypeVar("T")


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    path = db_path or settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(
        str(path),
        check_same_thread=False,
        timeout=CONNECT_TIMEOUT_S,
    )
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(f"PRAGMA busy_timeout = {BUSY_TIMEOUT_MS}")
    conn.execute("PRAGMA synchronous = NORMAL")
    return conn


def with_retry(
    fn: Callable[[], T],
    *,
    attempts: int = 8,
    delay_seconds: float = 0.05,
) -> T:
    """Retry a write when SQLite reports a transient lock."""
    last: Exception | None = None
    for attempt in range(1, max(1, attempts) + 1):
        try:
            return fn()
        except sqlite3.OperationalError as exc:
            last = exc
            if "locked" not in str(exc).lower() or attempt >= attempts:
                raise
            time.sleep(delay_seconds * attempt)
    assert last is not None
    raise last


@contextmanager
def get_connection(db_path: Path | None = None) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


@contextmanager
def transaction(conn: sqlite3.Connection) -> Iterator[sqlite3.Connection]:
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise


def fetchall(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> list[sqlite3.Row]:
    return list(conn.execute(sql, params).fetchall())


def fetchone(
    conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()
) -> sqlite3.Row | None:
    return conn.execute(sql, params).fetchone()


def execute(conn: sqlite3.Connection, sql: str, params: Sequence[Any] = ()) -> sqlite3.Cursor:
    return conn.execute(sql, params)


def executemany(
    conn: sqlite3.Connection, sql: str, params_seq: Sequence[Sequence[Any]]
) -> sqlite3.Cursor:
    return conn.executemany(sql, params_seq)
