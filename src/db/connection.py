"""SQLite connection helpers with parameterized queries and transactions."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Sequence

from src.config import get_settings


def connect(db_path: Path | None = None) -> sqlite3.Connection:
    settings = get_settings()
    path = db_path or settings.database_path
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    return conn


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
