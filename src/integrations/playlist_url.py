"""Parse YouTube Music playlist URLs into playlist IDs."""

from __future__ import annotations

import re
from urllib.parse import parse_qs, urlparse

from src.integrations.music_scope import is_youtube_music_host

_PLAYLIST_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{10,}$")


def extract_playlist_id(value: str) -> str | None:
    """Accept a raw playlist ID or a music.youtube.com playlist URL."""
    if not value:
        return None
    text = value.strip()
    if _PLAYLIST_ID_RE.match(text) and (" " not in text) and ("http" not in text.lower()):
        return text

    parsed = urlparse(text)
    if not parsed.scheme:
        # Maybe "PL..." with query noise
        if "list=" in text:
            qs = parse_qs(text.split("?", 1)[-1])
            cand = (qs.get("list") or [None])[0]
            return cand if cand and _PLAYLIST_ID_RE.match(cand) else None
        return text if _PLAYLIST_ID_RE.match(text) else None

    if parsed.netloc and not is_youtube_music_host(parsed.netloc):
        return None

    qs = parse_qs(parsed.query)
    if "list" in qs and qs["list"]:
        cand = qs["list"][0]
        return cand if _PLAYLIST_ID_RE.match(cand) else cand

    # Path forms: /playlist?list=... already handled; /browse/VLxxxx or /playlist/PLxxxx
    parts = [p for p in parsed.path.split("/") if p]
    for part in parts:
        if part.startswith(("PL", "OL", "LL", "RD", "VL", "UU", "LM")) and _PLAYLIST_ID_RE.match(part):
            return part.removeprefix("VL") if part.startswith("VL") else part
    return None


def playlist_url(playlist_id: str) -> str:
    return f"https://music.youtube.com/playlist?list={playlist_id}"


def track_url(video_id: str) -> str:
    return f"https://music.youtube.com/watch?v={video_id}"
