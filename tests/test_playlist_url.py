"""Playlist / track URL helpers."""

from src.integrations.playlist_url import extract_playlist_id, playlist_url, track_url


def test_extract_raw_playlist_id() -> None:
    assert extract_playlist_id("PLabcdefghijklmnopqrstuv") == "PLabcdefghijklmnopqrstuv"


def test_extract_from_music_url() -> None:
    url = "https://music.youtube.com/playlist?list=PLabcdefghijklmnopqrstuv"
    assert extract_playlist_id(url) == "PLabcdefghijklmnopqrstuv"


def test_extract_rejects_youtube_url() -> None:
    url = "https://www.youtube.com/playlist?list=OLabcdefghijklmnopqrstuv"
    assert extract_playlist_id(url) is None


def test_extract_rejects_empty() -> None:
    assert extract_playlist_id("") is None
    assert extract_playlist_id("   ") is None


def test_playlist_and_track_urls() -> None:
    assert playlist_url("PLabc") == "https://music.youtube.com/playlist?list=PLabc"
    assert track_url("xyz") == "https://music.youtube.com/watch?v=xyz"
