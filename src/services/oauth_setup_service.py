"""Local Google OAuth setup for one user on one machine."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from src.config import PROJECT_ROOT, Settings, get_settings, reload_env
from src.services.env_file import upsert_env_values


@dataclass(frozen=True)
class AuthStatus:
    client_id_set: bool
    client_secret_set: bool
    auth_file_exists: bool
    auth_file: Path
    ready: bool
    message: str


def auth_status(settings: Settings | None = None) -> AuthStatus:
    settings = settings or get_settings()
    client_id_set = bool(settings.client_id)
    client_secret_set = bool(settings.client_secret)
    auth_file_exists = settings.auth_file.exists()
    ready = client_id_set and client_secret_set and auth_file_exists
    if ready:
        message = "Google OAuth is ready."
    elif not client_id_set or not client_secret_set:
        message = "Add your Google OAuth client ID and client secret."
    else:
        message = "Sign in with Google to create the local auth file."
    return AuthStatus(
        client_id_set=client_id_set,
        client_secret_set=client_secret_set,
        auth_file_exists=auth_file_exists,
        auth_file=settings.auth_file,
        ready=ready,
        message=message,
    )


def save_oauth_client(
    *,
    client_id: str,
    client_secret: str,
    env_path: Path | None = None,
    auth_file: Path | None = None,
) -> Path:
    """Write OAuth client values to .env. Returns the auth file path."""
    client_id = client_id.strip()
    client_secret = client_secret.strip()
    if not client_id or not client_secret:
        raise ValueError("Client ID and client secret are required.")

    settings = get_settings()
    env_path = env_path or (PROJECT_ROOT / ".env")
    auth_file = auth_file or settings.auth_file
    if not auth_file.is_absolute():
        auth_file = PROJECT_ROOT / auth_file
    auth_file.parent.mkdir(parents=True, exist_ok=True)

    values = {
        "YTMUSIC_AUTH_MODE": "oauth",
        "YTMUSIC_AUTH_FILE": _relative_to_root(auth_file),
        "YTMUSIC_CLIENT_ID": client_id,
        "YTMUSIC_CLIENT_SECRET": client_secret,
    }
    upsert_env_values(env_path, values)
    for key, value in values.items():
        os.environ[key] = value
    reload_env(override=True)
    return auth_file


def run_device_oauth(
    *,
    client_id: str,
    client_secret: str,
    auth_file: Path,
    open_browser: bool = True,
) -> Path:
    """Run the Google device OAuth flow and write oauth.json."""
    from ytmusicapi import setup_oauth

    auth_file.parent.mkdir(parents=True, exist_ok=True)
    setup_oauth(
        client_id=client_id.strip(),
        client_secret=client_secret.strip(),
        filepath=str(auth_file),
        open_browser=open_browser,
    )
    return auth_file


def _relative_to_root(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(PROJECT_ROOT.resolve()))
    except ValueError:
        return str(path)
