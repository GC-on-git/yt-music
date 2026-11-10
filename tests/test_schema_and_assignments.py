"""Schema init and local assignment behaviour."""

from __future__ import annotations

from src.db.dedupe_tracks import dedupe_tracks_by_title_artist
from src.db.schema import SCHEMA_VERSION, get_schema_version
from src.services.assignment_service import AssignmentService, is_predesigned_playlist
from tests.conftest import seed_source_playlist, seed_track


def test_schema_migrates_to_current(conn) -> None:
    assert get_schema_version(conn) == SCHEMA_VERSION


def test_assign_unassign_and_undo(repo) -> None:
    track_id = seed_track(repo)
    service = AssignmentService(repo)
    dest_id = service.create_destination("Focus")

    service.assign(track_id, dest_id)
    assert repo.get_assignment_destination_ids(track_id) == [dest_id]

    service.unassign(track_id, dest_id)
    assert repo.get_assignment_destination_ids(track_id) == []

    service.assign(track_id, dest_id)
    assert service.undo() is True
    assert repo.get_assignment_destination_ids(track_id) == []


def test_destination_name_required(repo) -> None:
    service = AssignmentService(repo)
    try:
        service.create_destination("  ")
        raised = False
    except ValueError:
        raised = True
    assert raised


def test_update_destination_name_and_description(repo) -> None:
    service = AssignmentService(repo)
    dest_id = service.create_destination("Gym", "Workouts")
    service.update_destination(
        dest_id,
        name="Gym energy",
        description="High tempo",
        set_description=True,
    )
    dest = next(item for item in repo.list_destinations() if item.id == dest_id)
    assert dest.name == "Gym energy"
    assert dest.description == "High tempo"
    service.update_destination(dest_id, description="", set_description=True)
    dest = next(item for item in repo.list_destinations() if item.id == dest_id)
    assert dest.description is None


def test_merge_destinations_moves_tracks_and_deletes_sources(repo) -> None:
    service = AssignmentService(repo)
    keep_id = service.create_destination("Focus", "Deep work")
    source_id = service.create_destination("Concentration")
    other_id = service.create_destination("Ambient")
    t1 = seed_track(repo, video_id="v1", title="Song 1")
    t2 = seed_track(repo, video_id="v2", title="Song 2")
    t3 = seed_track(repo, video_id="v3", title="Song 3")
    service.assign(t1, keep_id)
    service.assign(t1, source_id)  # already on keep; merge should not duplicate
    service.assign(t2, source_id)
    service.assign(t3, other_id)

    moved = service.merge_destinations(
        [source_id, keep_id],
        keep_id,
        name="Focus deep",
        description="Merged focus sets",
        set_description=True,
    )
    names = {item.name for item in repo.list_destinations()}
    assert names == {"Focus deep", "Ambient"}
    assert moved == 1
    assert set(repo.get_assignment_destination_ids(t1)) == {keep_id}
    assert set(repo.get_assignment_destination_ids(t2)) == {keep_id}
    assert set(repo.get_assignment_destination_ids(t3)) == {other_id}
    keep = next(item for item in repo.list_destinations() if item.id == keep_id)
    assert keep.description == "Merged focus sets"


def test_tracks_unique_by_title_and_artist(repo) -> None:
    a = repo.upsert_track(
        video_id=None,
        title="Same",
        artists="Artist",
        album=None,
        duration_seconds=None,
        duration_text=None,
        canonical_url=None,
        thumbnail_url=None,
        availability="missing_id",
    )
    b = repo.upsert_track(
        video_id="vid-new",
        title=" same ",
        artists="Artist",
        album="Album",
        duration_seconds=120,
        duration_text="2:00",
        canonical_url="https://music.youtube.com/watch?v=vid-new",
        thumbnail_url=None,
        availability="available",
    )
    assert a == b
    row = repo.get_track(a)
    assert row is not None
    assert row["video_id"] == "vid-new"
    assert row["album"] == "Album"


def test_different_artists_are_not_merged(repo) -> None:
    a = seed_track(repo, video_id="v1", title="Same", artists="One")
    b = seed_track(repo, video_id="v2", title="Same", artists="Two")
    assert a != b


def test_excluded_source_playlists_become_predesigned_destinations(repo) -> None:
    service = AssignmentService(repo)
    keep = seed_track(repo, video_id="k1", title="Keep Song", artists="A")
    skip = seed_track(repo, video_id="s1", title="Skip Song", artists="B")
    seed_source_playlist(
        repo,
        playlist_id="PLkeep",
        title="Workout Videos",
        track_ids=[keep, skip],
        include_in_smart_assign=False,
    )
    seed_source_playlist(
        repo,
        playlist_id="PLsmart",
        title="Music dump",
        track_ids=[keep],
        include_in_smart_assign=True,
    )

    result = service.sync_predesigned_from_excluded_sources()
    assert result["created"] == 1
    assert result["excluded"] == 1
    dest = repo.get_destination_by_name("Workout Videos")
    assert dest is not None
    assert is_predesigned_playlist(dest.description)
    assert set(repo.get_assignment_destination_ids(keep)) == {dest.id}
    assert set(repo.get_assignment_destination_ids(skip)) == {dest.id}

    # Re-including the source removes the auto pre-designed destination.
    source_id = next(p["id"] for p in repo.list_source_playlists() if p["title"] == "Workout Videos")
    repo.set_source_playlist_smart_assign(source_id, True)
    removed = service.sync_predesigned_from_excluded_sources()
    assert removed["removed"] == 1
    assert repo.get_destination_by_name("Workout Videos") is None


def test_dedupe_merges_existing_duplicate_rows(repo) -> None:
    from src.db.dedupe_tracks import ensure_title_artist_unique_index

    keep = seed_track(repo, video_id="keep", title="Dup Song", artists="Band")
    repo.conn.execute("DROP INDEX IF EXISTS idx_tracks_title_artists_unique")
    cur = repo.conn.execute(
        """
        INSERT INTO tracks (video_id, title, artists, availability)
        VALUES ('drop', 'Dup Song', 'Band', 'available')
        """
    )
    drop_id = int(cur.lastrowid)
    dest = repo.create_destination("Gym")
    repo.assign_track(drop_id, dest)
    repo.conn.commit()

    removed = dedupe_tracks_by_title_artist(repo.conn)
    ensure_title_artist_unique_index(repo.conn)
    repo.conn.commit()
    assert removed == 1
    assert repo.get_track(drop_id) is None
    assert repo.get_assignment_destination_ids(keep) == [dest]
