"""CLI argument forwarding."""

from __future__ import annotations

import pytest

from src.cli import main, setup_auth


def test_auth_forwards_output(monkeypatch) -> None:
    captured: dict[str, list[str] | None] = {}

    def fake_setup(argv: list[str] | None = None) -> int:
        captured["argv"] = argv
        return 0

    monkeypatch.setattr("src.cli.setup_auth", fake_setup)
    assert main(["auth", "--output", "data/oauth.json"]) == 0
    assert captured["argv"] == ["--output", "data/oauth.json"]


def test_setup_auth_help() -> None:
    with pytest.raises(SystemExit) as exc:
        setup_auth(["--help"])
    assert exc.value.code == 0


def test_auth_rejects_browser_mode() -> None:
    with pytest.raises(SystemExit) as exc:
        setup_auth(["--mode", "browser"])
    assert exc.value.code == 2
