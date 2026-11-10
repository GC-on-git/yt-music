"""Protocol for YouTube Music integrations (replaceable without UI changes)."""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from src.models.domain import RemoteTrack, SourcePlaylistInfo


@runtime_checkable
class YouTubeMusicClient(Protocol):
    """Adapter contract for library import and optional remote writes."""

    def is_authenticated(self) -> bool: ...

    def auth_status_message(self) -> str: ...

    def list_library_playlists(self) -> list[SourcePlaylistInfo]: ...

    def get_playlist(
        self,
        playlist_id: str,
        *,
        progress_callback: Any | None = None,
        known: SourcePlaylistInfo | None = None,
    ) -> tuple[SourcePlaylistInfo, list[RemoteTrack]]: ...

    def create_playlist(self, title: str, description: str = "") -> str: ...

    def add_tracks_to_playlist(self, playlist_id: str, video_ids: list[str]) -> dict[str, Any]: ...

    def get_playlist_track_ids(self, playlist_id: str) -> list[str]: ...

    def supports_remote_writes(self) -> bool: ...

    def own_channel_ids(self) -> set[str]: ...

    def upload_playlist_ids(self) -> set[str]: ...
