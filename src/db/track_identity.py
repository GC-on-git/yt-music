"""Normalize and match tracks by title + artist."""

from __future__ import annotations

import re


_SPACE_RE = re.compile(r"\s+")


def normalize_track_text(value: str | None) -> str:
    return _SPACE_RE.sub(" ", str(value or "").strip()).lower()


def track_identity_key(title: str | None, artists: str | None) -> tuple[str, str]:
    return normalize_track_text(title), normalize_track_text(artists)
