"""SQLite busy-lock retry helper."""

from __future__ import annotations

import sqlite3

import pytest

from src.db.connection import with_retry


def test_with_retry_succeeds_after_lock() -> None:
    calls = {"n": 0}

    def flaky() -> str:
        calls["n"] += 1
        if calls["n"] < 3:
            raise sqlite3.OperationalError("database is locked")
        return "ok"

    assert with_retry(flaky, attempts=5, delay_seconds=0.001) == "ok"
    assert calls["n"] == 3


def test_with_retry_raises_non_lock() -> None:
    with pytest.raises(sqlite3.OperationalError, match="readonly"):
        with_retry(lambda: (_ for _ in ()).throw(sqlite3.OperationalError("readonly")))
