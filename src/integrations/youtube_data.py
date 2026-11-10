"""Official YouTube Data API v3 client using the local OAuth token.

YouTube Music's unofficial InnerTube endpoints reject OAuth with HTTP 400
("Request contains an invalid argument"). The same token works against
https://www.googleapis.com/youtube/v3.

Library listing still uses Data API playlists (mine=true), then music_scope
drops YouTube system lists and non-music videos so import stays YT Music oriented.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any, Callable
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from src.config import Settings, get_settings
from src.integrations.music_scope import is_non_music_system_playlist, video_looks_like_music
from src.integrations.playlist_url import playlist_url, track_url
from src.integrations.ytmusic_adapter import AuthenticationUnavailableError, YouTubeMusicAdapterError
from src.logging_config import get_logger, safe_error_message
from src.models.domain import AvailabilityStatus, RemoteTrack, SourcePlaylistInfo

logger = get_logger(__name__)

YOUTUBE_API = "https://www.googleapis.com/youtube/v3"
TOKEN_URL = "https://oauth2.googleapis.com/token"
_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


HttpFn = Callable[[str, str, dict[str, str], dict[str, str] | None, Any | None], dict[str, Any]]


class YoutubeDataApiAdapter:
    """YouTubeMusicClient implementation backed by YouTube Data API v3."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        http: HttpFn | None = None,
        authenticated: bool | None = None,
    ) -> None:
        self.settings = settings or get_settings()
        self._http = http or _default_http
        self._init_error: str | None = None
        self._token: dict[str, Any] | None = None
        self._own_channel_ids: set[str] | None = None
        self._upload_playlist_ids: set[str] | None = None
        if authenticated is not None:
            self._authenticated = authenticated
            return
        self._authenticated = self._load_token()

    def _load_token(self) -> bool:
        if not self.settings.client_id or not self.settings.client_secret:
            self._init_error = "OAuth mode requires YTMUSIC_CLIENT_ID and YTMUSIC_CLIENT_SECRET."
            return False
        path = self.settings.auth_file
        if not path.exists():
            self._init_error = (
                f"Auth file not found at {path}. Open Setup and sign in."
            )
            return False
        try:
            self._token = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            self._init_error = f"Could not read OAuth file: {exc}"
            return False
        if not self._token.get("access_token") and not self._token.get("refresh_token"):
            self._init_error = "OAuth file is missing access_token/refresh_token."
            return False
        return True

    def is_authenticated(self) -> bool:
        return bool(self._authenticated)

    def auth_status_message(self) -> str:
        if self.is_authenticated():
            return "Signed in."
        if self._init_error:
            return (
                f"Not authenticated. {self._init_error} "
                "Public/accessible playlist URL import is still available."
            )
        return "Open Setup and sign in with Google to import your library."

    def supports_remote_writes(self) -> bool:
        return self.is_authenticated()

    def own_channel_ids(self) -> set[str]:
        self._load_own_channels()
        return set(self._own_channel_ids or ())

    def upload_playlist_ids(self) -> set[str]:
        self._load_own_channels()
        return set(self._upload_playlist_ids or ())

    def _load_own_channels(self) -> None:
        if self._own_channel_ids is not None:
            return
        self._own_channel_ids = set()
        self._upload_playlist_ids = set()
        if not self.is_authenticated():
            return
        try:
            for item in self._paginate("channels", {"part": "id,contentDetails", "mine": "true"}):
                cid = item.get("id")
                if cid:
                    self._own_channel_ids.add(str(cid))
                uploads = (
                    ((item.get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
                )
                if uploads:
                    self._upload_playlist_ids.add(str(uploads))
        except Exception as exc:  # noqa: BLE001
            logger.warning("Could not list own channels: %s", safe_error_message(exc))

    def list_library_playlists(self) -> list[SourcePlaylistInfo]:
        self._require_auth()
        results: list[SourcePlaylistInfo] = []
        for item in self._paginate(
            "playlists",
            {
                "part": "snippet,contentDetails,status",
                "mine": "true",
                "maxResults": "50",
            },
        ):
            pid = item.get("id")
            snippet = item.get("snippet") or {}
            title = str(snippet.get("title") or "Untitled playlist")
            if not pid or is_non_music_system_playlist(str(pid), title):
                continue
            if str(pid) in self.upload_playlist_ids() or str(pid).removeprefix("VL") in self.upload_playlist_ids():
                continue
            details = item.get("contentDetails") or {}
            status = item.get("status") or {}
            results.append(
                SourcePlaylistInfo(
                    playlist_id=str(pid),
                    title=title,
                    url=playlist_url(str(pid)),
                    privacy=status.get("privacyStatus"),
                    description=snippet.get("description"),
                    track_count_remote=_coerce_int(details.get("itemCount")),
                    owned=True,
                    raw=item,
                )
            )
        return results

    def get_playlist(
        self,
        playlist_id: str,
        *,
        progress_callback: Callable[[str], None] | None = None,
        known: SourcePlaylistInfo | None = None,
    ) -> tuple[SourcePlaylistInfo, list[RemoteTrack]]:
        self._require_auth()
        if progress_callback:
            progress_callback(f"Fetching playlist {playlist_id}…")

        items = list(
            self._paginate(
                "playlistItems",
                {
                    "part": "snippet,contentDetails,status",
                    "playlistId": playlist_id,
                    "maxResults": "50",
                },
            )
        )

        if known is not None:
            info = SourcePlaylistInfo(
                playlist_id=playlist_id,
                title=known.title or playlist_id,
                url=known.url or playlist_url(playlist_id),
                privacy=known.privacy,
                description=known.description,
                track_count_remote=known.track_count_remote or len(items),
                owned=known.owned,
                raw=known.raw,
            )
        else:
            meta = self._first_or_none(
                self._paginate(
                    "playlists",
                    {"part": "snippet,contentDetails,status", "id": playlist_id},
                )
            ) or {}
            snippet = meta.get("snippet") or {}
            details = meta.get("contentDetails") or {}
            status = meta.get("status") or {}
            info = SourcePlaylistInfo(
                playlist_id=playlist_id,
                title=str(snippet.get("title") or playlist_id),
                url=playlist_url(playlist_id),
                privacy=status.get("privacyStatus"),
                description=snippet.get("description"),
                track_count_remote=_coerce_int(details.get("itemCount")) or len(items),
                owned=None,
                raw=meta,
            )

        video_ids = [
            str(
                (it.get("contentDetails") or {}).get("videoId")
                or (it.get("snippet") or {}).get("resourceId", {}).get("videoId")
                or ""
            )
            for it in items
        ]
        video_ids = [v for v in video_ids if v]
        extras = self._video_extras(video_ids) if self.settings.fetch_video_details else {}

        tracks: list[RemoteTrack] = []
        for idx, item in enumerate(items):
            tracks.append(_track_from_playlist_item(item, idx, extras))
            if progress_callback and idx and idx % 100 == 0:
                progress_callback(f"Parsed {idx} tracks from {info.title}…")
        return info, tracks

    def create_playlist(self, title: str, description: str = "") -> str:
        self._require_auth()
        data = self._api(
            "POST",
            "playlists",
            params={"part": "snippet,status"},
            body={
                "snippet": {"title": title, "description": description or ""},
                "status": {"privacyStatus": "private"},
            },
        )
        pid = data.get("id")
        if not pid:
            raise YouTubeMusicAdapterError(f"Create playlist returned no id: {data!r}")
        return str(pid)

    def add_tracks_to_playlist(self, playlist_id: str, video_ids: list[str]) -> dict[str, Any]:
        self._require_auth()
        added = 0
        for video_id in video_ids:
            try:
                self._api(
                    "POST",
                    "playlistItems",
                    params={"part": "snippet"},
                    body={
                        "snippet": {
                            "playlistId": playlist_id,
                            "resourceId": {"kind": "youtube#video", "videoId": video_id},
                        }
                    },
                )
                added += 1
            except YouTubeMusicAdapterError as exc:
                msg = str(exc).lower()
                if "duplicate" in msg or "already" in msg:
                    added += 1
                    continue
                raise
        return {"status": "STATUS_SUCCEEDED", "added": added}

    def get_playlist_track_ids(self, playlist_id: str) -> list[str]:
        _, tracks = self.get_playlist(playlist_id)
        return [t.video_id for t in tracks if t.video_id]

    def _video_extras(self, video_ids: list[str]) -> dict[str, dict[str, Any]]:
        extras: dict[str, dict[str, Any]] = {}
        unique = list(dict.fromkeys(video_ids))
        for i in range(0, len(unique), 50):
            chunk = unique[i : i + 50]
            for item in self._paginate(
                "videos",
                {
                    "part": "contentDetails,snippet,status,topicDetails",
                    "id": ",".join(chunk),
                },
            ):
                vid = item.get("id")
                if vid:
                    extras[str(vid)] = item
        return extras

    def _first_or_none(self, items: Any) -> dict[str, Any] | None:
        for item in items:
            return item
        return None

    def _paginate(self, resource: str, params: dict[str, str]) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        page_token: str | None = None
        while True:
            query = dict(params)
            if page_token:
                query["pageToken"] = page_token
            data = self._api("GET", resource, params=query)
            items.extend(data.get("items") or [])
            page_token = data.get("nextPageToken")
            if not page_token:
                break
        return items

    def _require_auth(self) -> None:
        if not self.is_authenticated():
            raise AuthenticationUnavailableError(
                self._init_error or "Library operations require OAuth. Open Setup and sign in."
            )

    def _ensure_access_token(self) -> str:
        if not self._token:
            raise AuthenticationUnavailableError("OAuth token is not loaded.")
        expires_at = _coerce_int(self._token.get("expires_at")) or 0
        if expires_at and expires_at < int(time.time()) + 60:
            self._refresh_token()
        token = self._token.get("access_token")
        if not token:
            self._refresh_token()
            token = self._token.get("access_token")
        if not token:
            raise AuthenticationUnavailableError(
                "OAuth access token is missing. Open Setup and sign in again."
            )
        return str(token)

    def _refresh_token(self) -> None:
        refresh = (self._token or {}).get("refresh_token")
        if not refresh:
            raise AuthenticationUnavailableError(
                "OAuth refresh_token is missing. Open Setup and sign in again."
            )
        logger.info("Refreshing YouTube OAuth access token.")
        data = self._http(
            "POST",
            TOKEN_URL,
            {"Content-Type": "application/x-www-form-urlencoded"},
            None,
            {
                "client_id": self.settings.client_id,
                "client_secret": self.settings.client_secret,
                "refresh_token": refresh,
                "grant_type": "refresh_token",
            },
        )
        access = data.get("access_token")
        if not access:
            raise AuthenticationUnavailableError("Token refresh did not return access_token.")
        assert self._token is not None
        self._token["access_token"] = access
        expires_in = _coerce_int(data.get("expires_in")) or 3600
        self._token["expires_in"] = expires_in
        self._token["expires_at"] = int(time.time()) + expires_in
        if data.get("refresh_token"):
            self._token["refresh_token"] = data["refresh_token"]
        self._write_token()

    def _write_token(self) -> None:
        path: Path = self.settings.auth_file
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self._token, indent=2), encoding="utf-8")

    def _api(
        self,
        method: str,
        resource: str,
        *,
        params: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
        _retried: bool = False,
    ) -> dict[str, Any]:
        token = self._ensure_access_token()
        headers = {
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
        }
        if body is not None:
            headers["Content-Type"] = "application/json"
        url = f"{YOUTUBE_API}/{resource}"
        try:
            return self._http(method, url, headers, params, body)
        except YouTubeMusicAdapterError as exc:
            text = str(exc)
            if (not _retried) and ("401" in text or "Invalid Credentials" in text or "authError" in text):
                self._refresh_token()
                return self._api(method, resource, params=params, body=body, _retried=True)
            raise


def _track_from_playlist_item(
    item: dict[str, Any], position: int, extras: dict[str, dict[str, Any]]
) -> RemoteTrack:
    snippet = item.get("snippet") or {}
    details = item.get("contentDetails") or {}
    status = item.get("status") or {}
    resource = snippet.get("resourceId") or {}
    video_id = details.get("videoId") or resource.get("videoId")
    title = str(snippet.get("title") or "Unknown title")
    extra = extras.get(str(video_id) or "") or {}
    extra_snippet = extra.get("snippet") or {}
    extra_details = extra.get("contentDetails") or {}
    extra_status = extra.get("status") or {}

    channel = extra_snippet.get("channelTitle") or snippet.get("videoOwnerChannelTitle")
    artists = [str(channel)] if channel else []
    duration_iso = extra_details.get("duration")
    duration_seconds = _parse_iso8601_duration(duration_iso)
    thumbs = (extra_snippet.get("thumbnails") or snippet.get("thumbnails") or {})
    thumb = None
    if isinstance(thumbs, dict):
        for key in ("high", "medium", "default"):
            node = thumbs.get(key)
            if isinstance(node, dict) and node.get("url"):
                thumb = node["url"]
                break

    privacy = (status.get("privacyStatus") or extra_status.get("privacyStatus") or "").lower()
    availability = AvailabilityStatus.AVAILABLE
    needs_review = False
    review_reason = None
    if not video_id:
        availability = AvailabilityStatus.MISSING_ID
        needs_review = True
        review_reason = "missing_video_id"
    elif privacy == "private" or "private video" in title.lower():
        availability = AvailabilityStatus.PRIVATE
        needs_review = True
        review_reason = "private_video"
    elif "deleted video" in title.lower():
        availability = AvailabilityStatus.UNAVAILABLE
        needs_review = True
        review_reason = "deleted_video"

    channel_id = extra_snippet.get("channelId") or snippet.get("videoOwnerChannelId")
    category_id = str(extra_snippet.get("categoryId") or "") or None
    topic_categories = list((extra.get("topicDetails") or {}).get("topicCategories") or [])
    music_verdict = video_looks_like_music(
        category_id=category_id,
        topic_categories=[str(t) for t in topic_categories],
    )
    is_song = True if music_verdict is None else music_verdict
    if music_verdict is False:
        availability = AvailabilityStatus.NON_SONG
        needs_review = True
        review_reason = f"non_song:{category_id or 'non_music'}"

    return RemoteTrack(
        video_id=str(video_id) if video_id else None,
        title=title,
        artists=artists,
        album=None,
        duration_seconds=duration_seconds,
        duration_text=_format_duration(duration_seconds),
        thumbnail_url=thumb,
        canonical_url=track_url(str(video_id)) if video_id else None,
        availability=availability,
        set_video_id=item.get("id"),
        position=snippet.get("position", position) if snippet.get("position") is not None else position,
        is_song=is_song,
        raw=item,
        needs_review=needs_review,
        review_reason=review_reason,
        channel_id=str(channel_id) if channel_id else None,
        channel_title=str(channel) if channel else None,
    )


def _parse_iso8601_duration(value: str | None) -> int | None:
    if not value:
        return None
    match = _DURATION_RE.fullmatch(value)
    if not match:
        return None
    hours, minutes, seconds = (int(part or 0) for part in match.groups())
    return hours * 3600 + minutes * 60 + seconds


def _format_duration(seconds: int | None) -> str | None:
    if seconds is None:
        return None
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def _coerce_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _default_http(
    method: str,
    url: str,
    headers: dict[str, str],
    params: dict[str, str] | None,
    body: Any | None,
) -> dict[str, Any]:
    if params:
        url = f"{url}?{urlencode(params)}"
    data: bytes | None = None
    hdrs = dict(headers)
    if body is not None:
        if hdrs.get("Content-Type", "").startswith("application/x-www-form-urlencoded"):
            data = urlencode(body).encode("utf-8")
        else:
            data = json.dumps(body).encode("utf-8")
            hdrs.setdefault("Content-Type", "application/json")
    request = Request(url, data=data, headers=hdrs, method=method)
    try:
        with urlopen(request, timeout=60) as response:
            raw = response.read().decode("utf-8")
            return json.loads(raw) if raw else {}
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
        message = _google_error_message(exc.code, detail)
        raise YouTubeMusicAdapterError(message) from exc
    except URLError as exc:
        raise YouTubeMusicAdapterError(f"Network error calling YouTube Data API: {exc.reason}") from exc


def _google_error_message(status: int, body: str) -> str:
    try:
        payload = json.loads(body)
        err = payload.get("error") or {}
        if isinstance(err, dict):
            text = err.get("message") or body
            reasons = []
            for item in err.get("errors") or []:
                if isinstance(item, dict) and item.get("reason"):
                    reasons.append(str(item["reason"]))
            reason_text = f" ({', '.join(reasons)})" if reasons else ""
            extra = ""
            if "accessNotConfigured" in reasons or "YouTube Data API" in str(text):
                extra = " Enable YouTube Data API v3 on this Google Cloud project."
            if "youtubeSignupRequired" in reasons:
                extra = " This Google account has no YouTube channel yet — open youtube.com once while signed in."
            if "quotaExceeded" in reasons or "dailyLimitExceeded" in reasons:
                clean = re.sub(r"<[^>]+>", "", str(text)).strip()
                return (
                    f"YouTube Data API daily quota exceeded ({status}): {clean}. "
                    "Default limit is 10,000 units/day and resets at midnight Pacific Time. "
                    "Check Quotas in Google Cloud Console, or wait and retry. "
                    "Import uses less quota now (video detail fetch is off by default)."
                )
            clean = re.sub(r"<[^>]+>", "", str(text)).strip()
            return f"YouTube Data API HTTP {status}: {clean}{reason_text}.{extra}"
    except json.JSONDecodeError:
        pass
    return f"YouTube Data API HTTP {status}: {body or 'unknown error'}"
