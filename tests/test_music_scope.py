"""YouTube Music scope helpers."""

from __future__ import annotations

from src.integrations.music_scope import (
    is_non_music_system_playlist,
    is_youtube_music_playlist_ref,
    should_import_track,
    video_looks_like_music,
)
from src.models.domain import AvailabilityStatus, RemoteTrack


def _track(*, is_song: bool = True, availability: AvailabilityStatus = AvailabilityStatus.AVAILABLE) -> RemoteTrack:
    return RemoteTrack(
        video_id="vid",
        title="Song",
        artists=["Artist"],
        album=None,
        duration_seconds=120,
        duration_text="2:00",
        thumbnail_url=None,
        canonical_url=None,
        availability=availability,
        set_video_id=None,
        position=0,
        is_song=is_song,
    )


def test_skips_system_playlists() -> None:
    assert is_non_music_system_playlist("WL")
    assert is_non_music_system_playlist("LL", "Liked videos")
    assert is_non_music_system_playlist("UUabc", "Uploads from Me")
    assert not is_non_music_system_playlist("LM", "Liked Music")
    assert not is_non_music_system_playlist("PLabc", "Focus")


def test_music_playlist_refs() -> None:
    assert is_youtube_music_playlist_ref("PLabcdefghijklmnopqrstuv")
    assert is_youtube_music_playlist_ref(
        "https://music.youtube.com/playlist?list=PLabcdefghijklmnopqrstuv"
    )
    assert not is_youtube_music_playlist_ref(
        "https://www.youtube.com/playlist?list=PLabcdefghijklmnopqrstuv"
    )


def test_video_music_heuristics() -> None:
    assert video_looks_like_music(category_id="10") is True
    assert video_looks_like_music(category_id="22") is False
    assert video_looks_like_music(video_type="MUSIC_VIDEO_TYPE_OMV") is True
    assert video_looks_like_music(video_type="UGC") is False
    assert video_looks_like_music() is None


def test_should_import_track() -> None:
    assert should_import_track(_track()) is True
    assert should_import_track(_track(is_song=False)) is False
    assert should_import_track(_track(availability=AvailabilityStatus.NON_SONG)) is False
