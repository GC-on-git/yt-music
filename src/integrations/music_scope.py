"""Bound import and playlist refs to YouTube Music content."""

from __future__ import annotations

from urllib.parse import urlparse

from src.models.domain import AvailabilityStatus, RemoteTrack

# YouTube system playlists that are not YouTube Music library shelves.
_SYSTEM_PLAYLIST_IDS = frozenset(
    {
        "WL",  # Watch Later
        "LL",  # Liked videos (YouTube). Liked Music is LM.
        "HL",  # History
        "DL",  # Downloads
        "FEplaylist_continuity",
    }
)

_SYSTEM_TITLE_PREFIXES = (
    "watch later",
    "liked videos",
    "favorites",
    "uploads from",
    "history",
)

_MUSIC_CATEGORY_ID = "10"
_MUSIC_TOPIC_MARKERS = (
    "/wiki/Music",
    "/wiki/Song",
    "/wiki/Album",
    "/wiki/Single_(music)",
    "/wiki/Extended_play",
)


def normalize_playlist_id(playlist_id: str) -> str:
    return playlist_id.removeprefix("VL").strip()


def is_non_music_system_playlist(playlist_id: str, title: str = "") -> bool:
    """True for Watch Later, Liked videos, uploads, and similar YouTube lists."""
    pid = normalize_playlist_id(playlist_id)
    if pid in _SYSTEM_PLAYLIST_IDS:
        return True
    if pid.startswith("UU"):
        return True
    lowered = (title or "").strip().lower()
    return any(lowered.startswith(prefix) for prefix in _SYSTEM_TITLE_PREFIXES)


def is_youtube_music_host(netloc: str) -> bool:
    host = (netloc or "").lower().split(":")[0]
    return host == "music.youtube.com" or host.endswith(".music.youtube.com")


def is_youtube_music_playlist_ref(value: str) -> bool:
    """Accept raw playlist IDs and music.youtube.com links only."""
    text = (value or "").strip()
    if not text:
        return False
    if "://" not in text and " " not in text and "http" not in text.lower():
        return True
    parsed = urlparse(text if "://" in text else f"https://{text}")
    return is_youtube_music_host(parsed.netloc)


def video_looks_like_music(
    *,
    category_id: str | None = None,
    topic_categories: list[str] | None = None,
    video_type: str | None = None,
) -> bool | None:
    """Return True/False when evidence exists, else None (unknown)."""
    vtype = (video_type or "").strip()
    if vtype:
        return "MUSIC_VIDEO_TYPE" in vtype

    if category_id == _MUSIC_CATEGORY_ID:
        return True
    if category_id:
        return False

    topics = topic_categories or []
    if topics:
        joined = " ".join(str(t) for t in topics)
        return any(marker in joined for marker in _MUSIC_TOPIC_MARKERS)

    return None


def should_import_track(track: RemoteTrack) -> bool:
    if not track.is_song:
        return False
    if track.availability == AvailabilityStatus.NON_SONG:
        return False
    return True
