"""Tests for local OAuth setup helpers."""

from __future__ import annotations

from pathlib import Path

import pytest

from src.config import Settings
from src.services.oauth_setup_service import auth_status, save_oauth_client


def _settings(tmp_path: Path, *, auth_file: Path | None = None) -> Settings:
    data_dir = tmp_path / "data"
    return Settings(
        database_path=tmp_path / "db.sqlite",
        auth_mode="oauth",
        auth_file=auth_file or (tmp_path / "oauth.json"),
        client_id="",
        client_secret="",
        brand_account=None,
        log_level="INFO",
        request_timeout_seconds=60,
        max_retries=3,
        retry_backoff_seconds=2.0,
        data_dir=data_dir,
        backup_dir=data_dir / "backups",
        llm_api_key="",
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.openai.com/v1",
        fetch_video_details=False,
    )


def test_auth_status_not_ready(tmp_path: Path) -> None:
    status = auth_status(_settings(tmp_path))
    assert status.ready is False
    assert "client" in status.message.lower()


def test_save_oauth_client_writes_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    env_path = tmp_path / ".env"
    auth_file = tmp_path / "data" / "oauth.json"
    monkeypatch.setattr("src.services.oauth_setup_service.PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(
        "src.services.oauth_setup_service.get_settings",
        lambda: _settings(tmp_path, auth_file=auth_file),
    )

    out = save_oauth_client(
        client_id=" id ",
        client_secret=" secret ",
        env_path=env_path,
        auth_file=auth_file,
    )
    assert out == auth_file
    text = env_path.read_text(encoding="utf-8")
    assert "YTMUSIC_CLIENT_ID=id" in text
    assert "YTMUSIC_CLIENT_SECRET=secret" in text
    assert "YTMUSIC_AUTH_MODE=oauth" in text


def test_save_oauth_client_requires_values() -> None:
    with pytest.raises(ValueError):
        save_oauth_client(client_id="", client_secret="x")
