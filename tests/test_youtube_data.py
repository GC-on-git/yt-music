"""YouTube Data API v3 adapter (OAuth) tests."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.config import Settings
from src.integrations.youtube_data import YoutubeDataApiAdapter, _parse_iso8601_duration
from src.integrations.ytmusic_adapter import YouTubeMusicAdapterError


def _settings(tmp_path: Path, token: dict[str, Any] | None = None) -> Settings:
    auth = tmp_path / "oauth.json"
    if token is not None:
        auth.write_text(__import__("json").dumps(token), encoding="utf-8")
    return Settings(
        database_path=tmp_path / "db.sqlite",
        auth_mode="oauth",
        auth_file=auth,
        client_id="cid",
        client_secret="csecret",
        brand_account=None,
        log_level="INFO",
        request_timeout_seconds=60,
        max_retries=3,
        retry_backoff_seconds=1,
        data_dir=tmp_path,
        backup_dir=tmp_path / "backups",
        llm_api_key="",
        llm_model="gpt-4o-mini",
        llm_base_url="https://api.openai.com/v1",
        fetch_video_details=True,
    )


def test_parse_duration() -> None:
    assert _parse_iso8601_duration("PT3M20S") == 200
    assert _parse_iso8601_duration("PT1H2M3S") == 3723
    assert _parse_iso8601_duration(None) is None


def test_list_library_playlists(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_at": 9999999999,
            "token_type": "Bearer",
        },
    )
    calls: list[tuple[str, str]] = []

    def http(method: str, url: str, headers: dict[str, str], params: dict[str, str] | None, body: Any):
        calls.append((method, url))
        assert headers["Authorization"] == "Bearer tok"
        if url.endswith("/channels"):
            return {"items": [{"id": "UCme", "contentDetails": {"relatedPlaylists": {"uploads": "UUme"}}}]}
        return {
            "items": [
                {
                    "id": "PLabc",
                    "snippet": {"title": "Gym", "description": ""},
                    "contentDetails": {"itemCount": 2},
                    "status": {"privacyStatus": "private"},
                },
                {
                    "id": "UUme",
                    "snippet": {"title": "Uploads from me"},
                    "contentDetails": {"itemCount": 3},
                    "status": {"privacyStatus": "public"},
                },
                {
                    "id": "WL",
                    "snippet": {"title": "Watch later"},
                    "contentDetails": {"itemCount": 9},
                    "status": {"privacyStatus": "private"},
                },
                {
                    "id": "LL",
                    "snippet": {"title": "Liked videos"},
                    "contentDetails": {"itemCount": 9},
                    "status": {"privacyStatus": "private"},
                },
            ]
        }

    client = YoutubeDataApiAdapter(settings, http=http)
    playlists = client.list_library_playlists()
    assert len(playlists) == 1
    assert playlists[0].title == "Gym"
    assert playlists[0].playlist_id == "PLabc"
    assert any(url.endswith("/playlists") for _, url in calls)


def test_get_playlist_tracks(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_at": 9999999999,
        },
    )

    def http(method: str, url: str, headers: dict[str, str], params: dict[str, str] | None, body: Any):
        resource = url.rsplit("/", 1)[-1]
        if resource == "playlists":
            return {
                "items": [
                    {
                        "id": "PLabc",
                        "snippet": {"title": "Focus"},
                        "contentDetails": {"itemCount": 1},
                        "status": {"privacyStatus": "private"},
                    }
                ]
            }
        if resource == "playlistItems":
            return {
                "items": [
                    {
                        "id": "item1",
                        "snippet": {
                            "title": "Song A",
                            "position": 0,
                            "resourceId": {"kind": "youtube#video", "videoId": "vid1"},
                            "videoOwnerChannelTitle": "Artist",
                        },
                        "contentDetails": {"videoId": "vid1"},
                    }
                ]
            }
        if resource == "videos":
            return {
                "items": [
                    {
                        "id": "vid1",
                        "snippet": {
                            "title": "Song A",
                            "channelTitle": "Artist",
                            "categoryId": "10",
                            "thumbnails": {},
                        },
                        "contentDetails": {"duration": "PT4M1S"},
                        "status": {"privacyStatus": "public"},
                        "topicDetails": {
                            "topicCategories": ["https://en.wikipedia.org/wiki/Music"]
                        },
                    }
                ]
            }
        raise YouTubeMusicAdapterError(f"unexpected {url}")

    client = YoutubeDataApiAdapter(settings, http=http)
    info, tracks = client.get_playlist("PLabc")
    assert info.title == "Focus"
    assert tracks[0].video_id == "vid1"
    assert tracks[0].duration_seconds == 241
    assert tracks[0].artists == ["Artist"]
    assert tracks[0].is_song is True


def test_non_music_video_marked(tmp_path: Path) -> None:
    settings = _settings(
        tmp_path,
        {
            "access_token": "tok",
            "refresh_token": "ref",
            "expires_at": 9999999999,
        },
    )

    def http(method: str, url: str, headers: dict[str, str], params: dict[str, str] | None, body: Any):
        resource = url.rsplit("/", 1)[-1]
        if resource == "playlists":
            return {
                "items": [
                    {
                        "id": "PLabc",
                        "snippet": {"title": "Mixed"},
                        "contentDetails": {"itemCount": 1},
                        "status": {"privacyStatus": "private"},
                    }
                ]
            }
        if resource == "playlistItems":
            return {
                "items": [
                    {
                        "id": "item1",
                        "snippet": {
                            "title": "Vlog",
                            "position": 0,
                            "resourceId": {"kind": "youtube#video", "videoId": "vid2"},
                        },
                        "contentDetails": {"videoId": "vid2"},
                    }
                ]
            }
        if resource == "videos":
            assert "topicDetails" in (params or {}).get("part", "")
            return {
                "items": [
                    {
                        "id": "vid2",
                        "snippet": {
                            "title": "Vlog",
                            "channelTitle": "Creator",
                            "categoryId": "22",
                            "thumbnails": {},
                        },
                        "contentDetails": {"duration": "PT10M"},
                        "status": {"privacyStatus": "public"},
                    }
                ]
            }
        raise YouTubeMusicAdapterError(f"unexpected {url}")

    client = YoutubeDataApiAdapter(settings, http=http)
    _, tracks = client.get_playlist("PLabc")
    assert tracks[0].is_song is False
    assert tracks[0].availability.value == "non_song"


def test_missing_auth_file(tmp_path: Path) -> None:
    settings = _settings(tmp_path, token=None)
    client = YoutubeDataApiAdapter(settings, http=lambda *a, **k: {})
    assert client.is_authenticated() is False
    with pytest.raises(Exception, match="Auth file not found"):
        client.list_library_playlists()
