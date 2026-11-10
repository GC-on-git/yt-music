"""Tests for .env read/write helpers."""

from __future__ import annotations

from pathlib import Path

from src.services.env_file import read_env_file, upsert_env_values


def test_upsert_creates_and_updates(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    upsert_env_values(path, {"A": "1", "B": "2"})
    assert read_env_file(path) == {"A": "1", "B": "2"}

    upsert_env_values(path, {"B": "9", "C": "3"})
    assert read_env_file(path) == {"A": "1", "B": "9", "C": "3"}


def test_upsert_keeps_comments(tmp_path: Path) -> None:
    path = tmp_path / ".env"
    path.write_text("# keep me\nA=1\n", encoding="utf-8")
    upsert_env_values(path, {"A": "2"})
    text = path.read_text(encoding="utf-8")
    assert "# keep me" in text
    assert "A=2" in text
