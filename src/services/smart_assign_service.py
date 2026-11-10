"""LLM-backed bulk assignment onto existing destination playlists."""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

from src.db.repository import Repository
from src.integrations.llm import LlmClient, LlmError
from src.models.domain import DestinationPlaylist
from src.services.assignment_service import AssignmentService, track_label

OTHERS_NAME = "Others"
LLM_CREATED_DESCRIPTION = "Created during smart assign for a missing mood or theme."
_EMPTY_LABELS = {
    "",
    "none",
    "null",
    "n/a",
    "na",
    "unknown",
    "unassigned",
    "unsure",
    "skip",
    "other",
    "others",
}

_SYSTEM = (
    "You assign every song to playlists. Reply with JSON only: "
    '{"assignments":[{"title":"...","artists":"...","playlists":["Name"]}]}. '
    "Prefer existing playlist names from the provided list. A song may belong to more than one. "
    "Playlists must be mood, vibe, or listening-context themes — not music genres. "
    "Good examples: Heartbreak, Party, Fun, Late Night Drive, Gym Energy, Chill Focus, "
    "Road Trip, Rainy Day, Feel Good, Soft & Slow, Dance Floor, Nostalgia. "
    "Do not create genre playlists such as Jazz, Indie, Pop, Rock, Hip-Hop, Metal, "
    "Classical, Country, EDM, Bollywood, K-Pop, or similar style/genre labels. "
    "If no existing playlist fits, propose a short theme name like the examples above. "
    'If still unsure, use "Others". Never leave a song without a playlist. '
    "Ignore spoken-word, uploads, and non-music by putting them in Others."
)

ProgressFn = Callable[[str], None]


@dataclass
class SmartAssignResult:
    assigned: int = 0
    skipped: int = 0
    processed: int = 0
    remaining: int = 0
    created_playlists: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)
    logs: list[str] = field(default_factory=list)


class SmartAssignService:
    def __init__(
        self,
        repo: Repository,
        assignments: AssignmentService,
        llm: LlmClient,
    ) -> None:
        self.repo = repo
        self.assignments = assignments
        self.llm = llm

    def run(
        self,
        *,
        batch_size: int = 40,
        progress: ProgressFn | None = None,
        should_continue: Callable[[], bool] | None = None,
    ) -> SmartAssignResult:
        """Process one batch of tracks that have not been smart-assigned yet."""
        result = SmartAssignResult()

        def log(msg: str) -> None:
            result.logs.append(msg)
            if progress:
                progress(msg)

        def still_running() -> bool:
            return should_continue() if should_continue else True

        if not self.llm.is_configured():
            result.errors.append("Set LLM_API_KEY in .env.")
            log("No LLM key configured.")
            return result

        batch_size = max(1, int(batch_size))
        pending_total = self.repo.count_pending_smart_assign()
        tracks = self.repo.pending_smart_assign(limit=batch_size)
        result.remaining = pending_total
        if not tracks:
            log("Nothing pending. Already smart-assigned tracks are not sent again.")
            return result

        if not still_running():
            log("Stopped before contacting the LLM.")
            return result

        dest_by_name = {d.name.lower(): d for d in self.repo.list_destinations()}
        dest_payload = [
            {"name": d.name, "description": d.description or ""} for d in dest_by_name.values()
        ]
        log(
            f"Batch of {len(tracks)} tracks "
            f"({pending_total} pending, model {self.llm.settings.llm_model})."
        )
        for row in tracks:
            log(f"  queued: {track_label(row['title'], row['artists'])}")

        log("Sending batch to LLM…")
        try:
            raw = self.llm.complete_json(_SYSTEM, json_payload(dest_payload, tracks))
        except LlmError as exc:
            result.errors.append(str(exc))
            log(f"LLM error: {exc}")
            return result

        if not still_running():
            log("Stopped after LLM reply. No tracks from this batch were marked done.")
            result.remaining = self.repo.count_pending_smart_assign()
            return result

        suggestions = _parse_assignments(raw)
        log(f"LLM returned {len(suggestions)} assignment(s).")
        index = {_key(row["title"], row["artists"]): int(row["id"]) for row in tracks}
        suggestion_by_id: dict[int, dict[str, Any]] = {}

        for item in suggestions:
            key = _key(item.get("title"), item.get("artists"))
            track_id = index.get(key)
            if track_id is None:
                log(f"  unmatched LLM row: {item.get('title')} — {item.get('artists')}")
                continue
            suggestion_by_id[track_id] = item

        for row in tracks:
            if not still_running():
                log("Stopped while applying assignments.")
                break
            track_id = int(row["id"])
            label = track_label(row["title"], row["artists"])
            names = _playlist_names(suggestion_by_id.get(track_id, {}))
            matched: list[str] = []
            for name in names:
                dest = self._playlist_for_name(name, dest_by_name, result, log)
                self.assignments.assign(track_id, dest.id)
                matched.append(dest.name)
            if not matched:
                dest = self._playlist_for_name(OTHERS_NAME, dest_by_name, result, log)
                self.assignments.assign(track_id, dest.id)
                matched.append(dest.name)
                log(f"  {label} → {dest.name} (no category)")
            else:
                log(f"  {label} → {', '.join(matched)}")
            self.repo.mark_smart_assigned([track_id])
            result.assigned += 1
            result.processed += 1

        result.remaining = self.repo.count_pending_smart_assign()
        extra = ""
        if result.created_playlists:
            extra = f" Created playlists: {', '.join(result.created_playlists)}."
        log(
            f"Batch complete. Assigned {result.assigned}. "
            f"{result.remaining} still pending.{extra}"
        )
        return result

    def _playlist_for_name(
        self,
        name: str,
        dest_by_name: dict[str, DestinationPlaylist],
        result: SmartAssignResult,
        log: ProgressFn,
    ) -> DestinationPlaylist:
        cleaned = _clean_playlist_name(name)
        if cleaned.lower() in _EMPTY_LABELS:
            cleaned = OTHERS_NAME
        existing = dest_by_name.get(cleaned.lower())
        if existing:
            return existing
        dest_id = self.assignments.create_destination(cleaned, LLM_CREATED_DESCRIPTION)
        dest = next(d for d in self.repo.list_destinations() if d.id == dest_id)
        dest_by_name[dest.name.lower()] = dest
        result.created_playlists.append(dest.name)
        log(f"  created playlist '{dest.name}'")
        return dest


_GENERATED_DESCRIPTIONS = {
    LLM_CREATED_DESCRIPTION,
    "Created during smart assign for a missing category.",
}


def is_generated_playlist(name: str, description: str | None = None) -> bool:
    from src.models.state_machines import DestinationOrigin

    return DestinationOrigin.from_playlist(name, description) == DestinationOrigin.GENERATED


def json_payload(destinations: list[dict[str, str]], tracks: list[Any]) -> str:
    return json.dumps(
        {
            "playlists": destinations,
            "tracks": [
                {
                    "title": row["title"],
                    "artists": row["artists"],
                    "album": row["album"],
                    "label": track_label(row["title"], row["artists"]),
                }
                for row in tracks
            ],
        },
        ensure_ascii=False,
    )


def _parse_assignments(raw: Any) -> list[dict[str, Any]]:
    if isinstance(raw, list):
        return [x for x in raw if isinstance(x, dict)]
    if isinstance(raw, dict):
        items = raw.get("assignments") or raw.get("tracks") or []
        if isinstance(items, list):
            return [x for x in items if isinstance(x, dict)]
    return []


def _key(title: Any, artists: Any) -> str:
    return f"{str(title or '').strip().lower()}|{str(artists or '').strip().lower()}"


def _playlist_names(item: dict[str, Any]) -> list[str]:
    raw = item.get("playlists", item.get("playlist"))
    if raw is None:
        return []
    if isinstance(raw, str):
        text = raw.strip()
        return [text] if text else []
    if isinstance(raw, list):
        return [str(name).strip() for name in raw if str(name).strip()]
    return []


def _clean_playlist_name(name: str) -> str:
    text = re.sub(r"\s+", " ", str(name or "")).strip(" \t\n\r\"'")
    text = text[:80].strip() or OTHERS_NAME
    return text
