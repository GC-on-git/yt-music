"""ytmusicapi-backed YouTube Music adapter.

ytmusicapi is an unofficial integration and may break if YouTube Music changes.
Authentication material is read only from local files configured via environment.
"""

from __future__ import annotations

import time
from typing import Any, Callable

from src.config import Settings, get_settings
from src.integrations.base import YouTubeMusicClient
from src.integrations.music_scope import is_non_music_system_playlist, video_looks_like_music
from src.integrations.playlist_url import playlist_url, track_url
from src.logging_config import get_logger, safe_error_message
from src.models.domain import AvailabilityStatus, RemoteTrack, SourcePlaylistInfo

logger = get_logger(__name__)

ProgressCallback = Callable[[str], None]


class YouTubeMusicAdapterError(Exception):
    pass


class AuthenticationUnavailableError(YouTubeMusicAdapterError):
    pass


class YTMusicAdapter:
    """Concrete adapter wrapping ytmusicapi.YTMusic."""

    def __init__(
        self,
        client: Any | None = None,
        settings: Settings | None = None,
        *,
        authenticated: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._client = client
        self._authenticated = authenticated
        self._init_error: str | None = None
        if self._client is None:
            self._client = self._build_client()

    def _build_client(self) -> Any | None:
        mode = self.settings.auth_mode
        try:
            from ytmusicapi import OAuthCredentials, YTMusic
        except ImportError as exc:
            self._init_error = f"ytmusicapi is not installed: {exc}"
            self._authenticated = False
            return None

        try:
            if mode == "none":
                self._authenticated = False
                return YTMusic()

            auth_file = self.settings.auth_file
            if not auth_file.exists():
                self._init_error = (
                    f"Auth file not found at {auth_file}. "
                    "Open Setup to sign in. Falling back to unauthenticated mode "
                    "(public/accessible playlists only)."
                )
                logger.warning(self._init_error)
                self._authenticated = False
                return YTMusic()

            if mode == "oauth":
                if not self.settings.client_id or not self.settings.client_secret:
                    self._init_error = (
                        "OAuth mode requires YTMUSIC_CLIENT_ID and YTMUSIC_CLIENT_SECRET. "
                        "Falling back to unauthenticated mode."
                    )
                    logger.warning(self._init_error)
                    self._authenticated = False
                    return YTMusic()
                credentials = OAuthCredentials(
                    client_id=self.settings.client_id,
                    client_secret=self.settings.client_secret,
                )
                client = YTMusic(
                    str(auth_file),
                    user=self.settings.brand_account,
                    oauth_credentials=credentials,
                )
                self._authenticated = True
                return client

            self._init_error = (
                f"Unknown auth mode '{mode}'. Use oauth (or none). Using unauthenticated client."
            )
            self._authenticated = False
            return YTMusic()
        except Exception as exc:  # noqa: BLE001 - surface as init error
            self._init_error = safe_error_message(exc)
            logger.error("Failed to initialize YTMusic client: %s", self._init_error)
            self._authenticated = False
            try:
                from ytmusicapi import YTMusic

                return YTMusic()
            except Exception:
                return None

    def is_authenticated(self) -> bool:
        return bool(self._authenticated)

    def auth_status_message(self) -> str:
        if self.is_authenticated():
            return f"Authenticated via {self.settings.auth_mode} ({self.settings.auth_file.name})."
        if self._init_error:
            return (
                f"Not authenticated. {self._init_error} "
                "Public/accessible playlist URL import is still available; "
                "a public account URL cannot access private playlists."
            )
        return "Open Setup and sign in with Google to import your library."

    def supports_remote_writes(self) -> bool:
        return self.is_authenticated()

    def own_channel_ids(self) -> set[str]:
        return set()

    def upload_playlist_ids(self) -> set[str]:
        return set()

    def _require_client(self) -> Any:
        if self._client is None:
            raise YouTubeMusicAdapterError(
                self._init_error or "YouTube Music client is unavailable."
            )
        return self._client

    def _with_retries(self, label: str, fn: Callable[[], Any]) -> Any:
        attempts = max(1, self.settings.max_retries)
        delay = self.settings.retry_backoff_seconds
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return fn()
            except Exception as exc:  # noqa: BLE001
                last_exc = exc
                msg = safe_error_message(exc)
                logger.warning("%s failed (attempt %s/%s): %s", label, attempt, attempts, msg)
                if attempt < attempts:
                    time.sleep(delay * attempt)
        raise YouTubeMusicAdapterError(
            f"{label} failed after {attempts} attempts: {safe_error_message(last_exc)}"
        )

    def list_library_playlists(self) -> list[SourcePlaylistInfo]:
        if not self.is_authenticated():
            raise AuthenticationUnavailableError(
                "Library playlist listing requires authentication. "
                "Use a playlist URL/ID import, or open Setup and sign in."
            )
        client = self._require_client()

        def _call() -> list[dict[str, Any]]:
            # limit=None retrieves all pages/continuations inside ytmusicapi
            return client.get_library_playlists(limit=None)

        raw_list = self._with_retries("get_library_playlists", _call)
        results: list[SourcePlaylistInfo] = []
        for item in raw_list or []:
            pid = item.get("playlistId") or item.get("id")
            if not pid:
                continue
            title = str(item.get("title") or "Untitled playlist")
            if is_non_music_system_playlist(str(pid), title):
                continue
            results.append(
                SourcePlaylistInfo(
                    playlist_id=str(pid),
                    title=title,
                    url=playlist_url(str(pid)),
                    privacy=None,
                    description=None,
                    track_count_remote=_coerce_int(item.get("count")),
                    owned=item.get("owned"),
                    raw=item,
                )
            )
        return results

    def get_playlist(
        self,
        playlist_id: str,
        *,
        progress_callback: ProgressCallback | None = None,
        known: SourcePlaylistInfo | None = None,
    ) -> tuple[SourcePlaylistInfo, list[RemoteTrack]]:
        client = self._require_client()
        if progress_callback:
            progress_callback(f"Fetching playlist {playlist_id}…")

        def _call() -> dict[str, Any]:
            # limit=None fetches all tracks with internal continuation handling
            return client.get_playlist(playlist_id, limit=None)

        data = self._with_retries(f"get_playlist:{playlist_id}", _call)
        info = SourcePlaylistInfo(
            playlist_id=str(data.get("id") or playlist_id),
            title=str((known.title if known and known.title else None) or data.get("title") or "Untitled playlist"),
            url=playlist_url(str(data.get("id") or playlist_id)),
            privacy=(known.privacy if known else None) or data.get("privacy"),
            description=(known.description if known else None) or data.get("description"),
            track_count_remote=_coerce_int(data.get("trackCount")),
            owned=known.owned if known else None,
            raw={k: v for k, v in data.items() if k != "tracks"},
        )
        tracks_raw = data.get("tracks") or []
        tracks: list[RemoteTrack] = []
        for idx, item in enumerate(tracks_raw):
            tracks.append(normalize_remote_track(item, position=idx))
            if progress_callback and idx and idx % 100 == 0:
                progress_callback(f"Parsed {idx} tracks from {info.title}…")
        return info, tracks

    def create_playlist(self, title: str, description: str = "") -> str:
        if not self.supports_remote_writes():
            raise AuthenticationUnavailableError(
                "Creating remote playlists requires authentication."
            )
        client = self._require_client()

        def _call() -> Any:
            return client.create_playlist(title, description or "", privacy_status="PRIVATE")

        result = self._with_retries("create_playlist", _call)
        if isinstance(result, str) and result:
            return result
        raise YouTubeMusicAdapterError(f"Unexpected create_playlist response: {result!r}")

    def add_tracks_to_playlist(self, playlist_id: str, video_ids: list[str]) -> dict[str, Any]:
        if not self.supports_remote_writes():
            raise AuthenticationUnavailableError(
                "Adding tracks to remote playlists requires authentication."
            )
        if not video_ids:
            return {"status": "STATUS_SUCCEEDED", "added": 0}
        client = self._require_client()

        def _call() -> Any:
            return client.add_playlist_items(playlist_id, video_ids, duplicates=False)

        result = self._with_retries("add_playlist_items", _call)
        if isinstance(result, dict):
            return result
        return {"status": str(result), "added": len(video_ids)}

    def get_playlist_track_ids(self, playlist_id: str) -> list[str]:
        _, tracks = self.get_playlist(playlist_id)
        return [t.video_id for t in tracks if t.video_id]


def normalize_remote_track(item: dict[str, Any], *, position: int) -> RemoteTrack:
    video_id = item.get("videoId")
    title = str(item.get("title") or "Unknown title")
    artists = _artist_names(item.get("artists"))
    album_obj = item.get("album")
    album = None
    if isinstance(album_obj, dict):
        album = album_obj.get("name")
    elif isinstance(album_obj, str):
        album = album_obj

    thumbnails = item.get("thumbnails") or []
    thumb = None
    if isinstance(thumbnails, list) and thumbnails:
        thumb = thumbnails[-1].get("url") if isinstance(thumbnails[-1], dict) else None

    is_available = item.get("isAvailable")
    video_type = str(item.get("videoType") or "")
    music_verdict = video_looks_like_music(video_type=video_type or None)
    # ytmusic rows without videoType are usually songs in library playlists.
    is_song = True if music_verdict is None else music_verdict

    availability = AvailabilityStatus.AVAILABLE
    needs_review = False
    review_reason = None

    if video_id is None:
        availability = AvailabilityStatus.MISSING_ID
        needs_review = True
        review_reason = "missing_video_id"
    elif is_available is False:
        availability = AvailabilityStatus.UNAVAILABLE
    elif is_available is None and not video_id:
        availability = AvailabilityStatus.UNKNOWN
        needs_review = True
        review_reason = "uncertain_availability"
    elif not is_song:
        availability = AvailabilityStatus.NON_SONG
        needs_review = True
        review_reason = f"non_song:{video_type or 'unknown_type'}"

    # Heuristic for private/restricted wording in titles
    lowered = title.lower()
    if "private video" in lowered:
        availability = AvailabilityStatus.PRIVATE
    elif "deleted video" in lowered or title == "[Deleted video]":
        availability = AvailabilityStatus.UNAVAILABLE

    return RemoteTrack(
        video_id=str(video_id) if video_id else None,
        title=title,
        artists=artists,
        album=album,
        duration_seconds=_coerce_int(item.get("duration_seconds")),
        duration_text=item.get("duration"),
        thumbnail_url=thumb,
        canonical_url=track_url(str(video_id)) if video_id else None,
        availability=availability,
        set_video_id=item.get("setVideoId"),
        position=position,
        is_song=is_song,
        raw=item,
        needs_review=needs_review,
        review_reason=review_reason,
    )


def _artist_names(artists: Any) -> list[str]:
    if not artists:
        return []
    if isinstance(artists, str):
        return [artists]
    names: list[str] = []
    for a in artists:
        if isinstance(a, dict) and a.get("name"):
            names.append(str(a["name"]))
        elif isinstance(a, str):
            names.append(a)
    return names


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def build_default_adapter(settings: Settings | None = None) -> YouTubeMusicClient:
    settings = settings or get_settings()
    if settings.auth_mode == "oauth":
        from src.integrations.youtube_data import YoutubeDataApiAdapter

        return YoutubeDataApiAdapter(settings=settings)
    return YTMusicAdapter(settings=settings)
