"""Shared pytest fixtures: in-memory SQLite + repository."""

from __future__ import annotations

import sqlite3

import pytest

from src.db.repository import Repository
from src.db.schema import init_db


@pytest.fixture
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    init_db(connection)
    yield connection
    connection.close()


@pytest.fixture
def repo(conn: sqlite3.Connection) -> Repository:
    return Repository(conn)


def seed_track(
    repo: Repository,
    *,
    video_id: str = "vid001",
    title: str = "Song A",
    artists: str = "Artist",
) -> int:
    return repo.upsert_track(
        video_id=video_id,
        title=title,
        artists=artists,
        album="Album",
        duration_seconds=180,
        duration_text="3:00",
        canonical_url=f"https://music.youtube.com/watch?v={video_id}",
        thumbnail_url=None,
        availability="available",
    )


def seed_source_playlist(
    repo: Repository,
    *,
    playlist_id: str = "PL1",
    title: str = "Liked",
    track_ids: list[int] | tuple[int, ...] = (),
    include_in_smart_assign: bool = True,
) -> int:
    local_id = repo.upsert_source_playlist(
        playlist_id=playlist_id,
        title=title,
        url=None,
        import_status="success",
    )
    repo.set_source_playlist_smart_assign(local_id, include_in_smart_assign)
    for position, track_id in enumerate(track_ids):
        repo.insert_playlist_item(
            track_id=track_id,
            source_playlist_id=local_id,
            position=position,
            set_video_id=None,
            import_run_id=None,
            availability="available",
            raw_title=None,
        )
    repo.conn.commit()
    return local_id
