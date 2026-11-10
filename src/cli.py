"""CLI helpers: OAuth setup and quick status checks."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from src.config import PROJECT_ROOT, get_settings
from src.logging_config import configure_logging, get_logger
from src.services.oauth_setup_service import auth_status, run_device_oauth

logger = get_logger(__name__)


def setup_auth(argv: list[str] | None = None) -> int:
    """Interactive Google account OAuth via ytmusicapi (device / TV client)."""
    parser = argparse.ArgumentParser(
        description="Set up Google OAuth for the organizer."
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Where to write the auth file (default from .env / data/oauth.json)",
    )
    args = parser.parse_args(argv)
    settings = get_settings()
    configure_logging(settings.log_level)

    out = Path(args.output) if args.output else settings.auth_file
    if not out.is_absolute():
        out = PROJECT_ROOT / out
    out.parent.mkdir(parents=True, exist_ok=True)

    print(
        "\nIMPORTANT:\n"
        "- ytmusicapi is an unofficial YouTube Music client and may break if Google changes APIs.\n"
        "- Never paste your Google password into this app.\n"
        "- Auth files stay local under data/ and are gitignored.\n"
        "- OAuth is the only supported login.\n"
        "- Prefer the Setup page in the Streamlit app for first-time setup.\n"
    )

    client_id = settings.client_id
    client_secret = settings.client_secret
    if not client_id or not client_secret:
        print(
            "Missing YTMUSIC_CLIENT_ID / YTMUSIC_CLIENT_SECRET in .env.\n"
            "Open the Setup page in the app, or follow docs/setup.md.\n"
        )
        return 1

    print(f"Starting Google OAuth device flow. Auth file → {out}")
    print(
        "Sign in with a Gmail listed as a Test user on this Cloud project's "
        "OAuth consent screen (Testing apps are not Google-verified)."
    )
    run_device_oauth(
        client_id=client_id,
        client_secret=client_secret,
        auth_file=out,
        open_browser=True,
    )
    print(f"Saved OAuth credentials to {out}")
    print("Set YTMUSIC_AUTH_MODE=oauth and YTMUSIC_AUTH_FILE to that path in .env.")
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(sys.argv[1:] if argv is None else argv)
    if raw[:1] == ["auth"]:
        return setup_auth(raw[1:])

    parser = argparse.ArgumentParser(description="YT Music Organizer utilities")
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("auth", help="Set up Google OAuth (device login)")
    sub.add_parser("status", help="Show auth/db status")
    args = parser.parse_args(raw)

    if args.command == "status":
        settings = get_settings()
        status = auth_status(settings)
        print(f"Database: {settings.database_path} (exists={settings.database_path.exists()})")
        print(f"Auth mode: {settings.auth_mode}")
        print(f"Auth file: {status.auth_file} (exists={status.auth_file_exists})")
        print(f"Client ID set: {status.client_id_set}")
        print(f"Ready: {status.ready}")
        return 0

    parser.print_help()
    return 0


if __name__ == "__main__":
    sys.exit(main())
