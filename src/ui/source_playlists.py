"""Filter helpers for the source-playlist picker."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence

PRIVACY_OPTIONS = ("Public", "Private", "Unlisted")
IMPORTED_WINDOWS = ("Any time", "Last 7 days", "Last 30 days", "Never imported")


def normalize_privacy(value: str | None) -> str:
    raw = (value or "").strip().lower()
    mapping = {"public": "Public", "private": "Private", "unlisted": "Unlisted"}
    return mapping.get(raw, "Unknown")


def parse_playlist_time(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value))
    except ValueError:
        return None


def utc_now() -> datetime:
    return datetime.now(timezone.utc).replace(tzinfo=None)


def filter_source_playlists(
    rows: Sequence[Mapping[str, Any]],
    *,
    search: str = "",
    privacies: Sequence[str] | None = None,
    imported: str = "Any time",
    now: datetime | None = None,
) -> list[Mapping[str, Any]]:
    query = search.strip().lower()
    wanted = {item for item in (privacies or []) if item}
    moment = now or utc_now()
    cutoff: datetime | None = None
    if imported == "Last 7 days":
        cutoff = moment - timedelta(days=7)
    elif imported == "Last 30 days":
        cutoff = moment - timedelta(days=30)

    visible: list[Mapping[str, Any]] = []
    for row in rows:
        if query and query not in str(row["title"]).lower():
            continue
        if wanted and normalize_privacy(_value(row, "privacy")) not in wanted:
            continue
        imported_at = parse_playlist_time(_value(row, "last_import_at"))
        if imported == "Never imported" and imported_at is not None:
            continue
        if cutoff is not None and (imported_at is None or imported_at < cutoff):
            continue
        visible.append(row)
    return visible


def _value(row: Mapping[str, Any], key: str) -> Any:
    if key not in row.keys():
        return None
    return row[key]
