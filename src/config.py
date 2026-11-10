"""Application configuration loaded from environment / .env."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")


def reload_env(*, override: bool = True) -> None:
    """Reload `.env` into process environment after Setup writes new values."""
    load_dotenv(PROJECT_ROOT / ".env", override=override)


def _path_from_env(key: str, default: str) -> Path:
    raw = os.getenv(key, default)
    path = Path(raw)
    if not path.is_absolute():
        path = PROJECT_ROOT / path
    return path


@dataclass(frozen=True)
class Settings:
    database_path: Path
    auth_mode: str
    auth_file: Path
    client_id: str
    client_secret: str
    brand_account: str | None
    log_level: str
    request_timeout_seconds: int
    max_retries: int
    retry_backoff_seconds: float
    data_dir: Path
    backup_dir: Path
    llm_api_key: str
    llm_model: str
    llm_base_url: str
    fetch_video_details: bool

    @property
    def is_authenticated_mode(self) -> bool:
        return self.auth_mode == "oauth"


def _env_bool(key: str, default: bool) -> bool:
    raw = (os.getenv(key) or "").strip().lower()
    if not raw:
        return default
    return raw in {"1", "true", "yes", "on"}


def get_settings() -> Settings:
    data_dir = PROJECT_ROOT / "data"
    return Settings(
        database_path=_path_from_env("DATABASE_PATH", "data/organizer.db"),
        auth_mode=(os.getenv("YTMUSIC_AUTH_MODE", "oauth") or "oauth").strip().lower(),
        auth_file=_path_from_env("YTMUSIC_AUTH_FILE", "data/oauth.json"),
        client_id=(os.getenv("YTMUSIC_CLIENT_ID") or "").strip(),
        client_secret=(os.getenv("YTMUSIC_CLIENT_SECRET") or "").strip(),
        brand_account=(os.getenv("YTMUSIC_BRAND_ACCOUNT") or "").strip() or None,
        log_level=(os.getenv("LOG_LEVEL", "INFO") or "INFO").strip().upper(),
        request_timeout_seconds=int(os.getenv("YTMUSIC_REQUEST_TIMEOUT_SECONDS", "60")),
        max_retries=int(os.getenv("YTMUSIC_MAX_RETRIES", "3")),
        retry_backoff_seconds=float(os.getenv("YTMUSIC_RETRY_BACKOFF_SECONDS", "2")),
        data_dir=data_dir,
        backup_dir=data_dir / "backups",
        llm_api_key=(os.getenv("LLM_API_KEY") or os.getenv("OPENAI_API_KEY") or "").strip(),
        llm_model=(os.getenv("LLM_MODEL") or "gpt-4o-mini").strip(),
        llm_base_url=(os.getenv("LLM_BASE_URL") or "https://api.openai.com/v1").strip().rstrip("/"),
        # Off by default: videos.list roughly doubles import quota use.
        fetch_video_details=_env_bool("YTMUSIC_FETCH_VIDEO_DETAILS", False),
    )
