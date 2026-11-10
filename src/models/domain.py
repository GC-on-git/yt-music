"""Typed domain models used across services and UI."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any


class AvailabilityStatus(str, Enum):
    AVAILABLE = "available"
    UNAVAILABLE = "unavailable"
    PRIVATE = "private"
    RESTRICTED = "restricted"
    UNKNOWN = "unknown"
    NON_SONG = "non_song"
    MISSING_ID = "missing_id"


class ImportStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    PARTIAL = "partial"
    FAILED = "failed"
    SKIPPED = "skipped"


class AssignmentStatus(str, Enum):
    UNASSIGNED = "unassigned"
    ASSIGNED = "assigned"
    MULTI_ASSIGNED = "multi_assigned"


class OperationType(str, Enum):
    CREATE_PLAYLIST = "create_playlist"
    ADD_TRACK = "add_track"
    VERIFY_PLAYLIST = "verify_playlist"


class OperationStatus(str, Enum):
    PENDING = "pending"
    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"


@dataclass
class SourcePlaylistInfo:
    playlist_id: str
    title: str
    url: str
    privacy: str | None = None
    description: str | None = None
    track_count_remote: int | None = None
    owned: bool | None = None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class RemoteTrack:
    video_id: str | None
    title: str
    artists: list[str]
    album: str | None
    duration_seconds: int | None
    duration_text: str | None
    thumbnail_url: str | None
    canonical_url: str | None
    availability: AvailabilityStatus
    set_video_id: str | None
    position: int
    is_song: bool = True
    raw: dict[str, Any] = field(default_factory=dict)
    needs_review: bool = False
    review_reason: str | None = None
    channel_id: str | None = None
    channel_title: str | None = None
    is_own_upload: bool = False


@dataclass
class TrackRecord:
    id: int
    video_id: str | None
    title: str
    artists: str
    album: str | None
    duration_seconds: int | None
    duration_text: str | None
    canonical_url: str | None
    thumbnail_url: str | None
    availability: str
    needs_review: bool
    review_reason: str | None
    first_seen_at: str
    last_seen_at: str


@dataclass
class DestinationPlaylist:
    id: int
    name: str
    description: str | None
    sort_order: int
    remote_playlist_id: str | None
    created_at: str
    updated_at: str


@dataclass
class ImportRunSummary:
    id: int
    started_at: str
    finished_at: str | None
    mode: str
    status: str
    playlists_total: int
    playlists_succeeded: int
    playlists_failed: int
    tracks_seen: int
    unique_tracks_upserted: int
    errors: list[str] = field(default_factory=list)


@dataclass
class DashboardStats:
    source_playlists: int
    playlist_entries: int
    unique_tracks: int
    duplicate_occurrences: int
    unavailable_or_uncertain: int
    assigned_tracks: int
    unassigned_tracks: int
    last_successful_import_at: str | None


@dataclass
class RemoteOperationPreview:
    operation_type: OperationType
    destination_local_id: int
    destination_name: str
    video_id: str | None = None
    track_title: str | None = None
    remote_playlist_id: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


@dataclass
class UndoEntry:
    action: str
    track_id: int
    destination_id: int | None
    previous_destination_ids: list[int]
    timestamp: datetime
