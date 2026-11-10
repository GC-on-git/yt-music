"""Title labels, own-upload exclusion, and LLM assign."""

from src.services.assignment_service import AssignmentService, labeled_track_map, track_label
from src.services.smart_assign_service import (
    LLM_CREATED_DESCRIPTION,
    SmartAssignService,
    is_generated_playlist,
)
from src.integrations.llm import LlmClient
from tests.conftest import seed_source_playlist, seed_track


def test_track_label() -> None:
    assert track_label("Song A", "Artist") == "Song A — Artist"


def test_toggle_keeps_other_playlists(repo) -> None:
    tid = seed_track(repo, title="Night Drive")
    service = AssignmentService(repo)
    gym = service.create_destination("Gym")
    drive = service.create_destination("Drive")
    service.assign(tid, gym)
    assert service.toggle(tid, drive) is True
    assert set(repo.get_assignment_destination_ids(tid)) == {gym, drive}
    assert service.toggle(tid, gym) is False
    assert repo.get_assignment_destination_ids(tid) == [drive]


def test_assign_by_label(repo) -> None:
    tid = seed_track(repo, title="Night Drive")
    service = AssignmentService(repo)
    dest = service.create_destination("Drive")
    mapping = labeled_track_map(repo.assignable_tracks())
    assert "Night Drive — Artist" in mapping
    service.assign_labels(["Night Drive — Artist"], mapping, dest)
    assert repo.get_assignment_destination_ids(tid) == [dest]


def test_generated_playlist_helper() -> None:
    assert is_generated_playlist("Others")
    assert is_generated_playlist("others")
    assert is_generated_playlist("Sufi", LLM_CREATED_DESCRIPTION)
    assert not is_generated_playlist("Gym")
    assert not is_generated_playlist("Gym", "Weekend mix")


def test_review_sorted_by_playlist_not_title(repo) -> None:
    zebra = seed_track(repo, video_id="z", title="Zebra")
    alpha = seed_track(repo, video_id="a", title="Alpha")
    service = AssignmentService(repo)
    gym = service.create_destination("Gym")
    chill = service.create_destination("Chill")
    service.assign(zebra, gym)
    service.assign(alpha, chill)
    titles = [r["title"] for r in repo.assigned_tracks_for_review()]
    assert titles == ["Zebra", "Alpha"]


def test_review_tracks_by_playlist_and_unsorted(repo) -> None:
    loose = seed_track(repo, video_id="u", title="Loose")
    gym_track = seed_track(repo, video_id="g", title="Pump")
    other_track = seed_track(repo, video_id="o", title="Filler")
    service = AssignmentService(repo)
    gym = service.create_destination("Gym")
    others = service.create_destination("Others", LLM_CREATED_DESCRIPTION)
    service.assign(gym_track, gym)
    service.assign(other_track, others)

    unsorted = [r["title"] for r in repo.assigned_tracks_for_review(unassigned_only=True)]
    gym_rows = [r["title"] for r in repo.assigned_tracks_for_review(destination_id=gym)]
    other_rows = [r["title"] for r in repo.assigned_tracks_for_review(destination_id=others)]
    counts = repo.destination_track_counts()

    assert unsorted == ["Loose"]
    assert gym_rows == ["Pump"]
    assert other_rows == ["Filler"]
    assert repo.count_unassigned_tracks() == 1
    assert counts[gym] == 1
    assert counts[others] == 1
    assert loose not in {gym_track, other_track}


def test_own_uploads_excluded(repo) -> None:
    seed_track(repo, video_id="mine1", title="My Upload")
    repo.conn.execute("UPDATE tracks SET is_own_upload = 1 WHERE video_id = 'mine1'")
    seed_track(repo, video_id="other", title="Real Song")
    rows, total = repo.catalogue_query()
    titles = {r["title"] for r in rows}
    assert "Real Song" in titles
    assert "My Upload" not in titles
    assert total == 1
    assert [r["title"] for r in repo.unassigned_tracks()] == ["Real Song"]


def test_smart_assign_uses_titles(repo) -> None:
    tid = seed_track(repo, title="Pump", artists="Gym Artist")
    seed_source_playlist(repo, track_ids=[tid])
    assignments = AssignmentService(repo)
    assignments.create_destination("Gym")

    def fake_complete(system: str, user: str):
        return {"assignments": [{"title": "Pump", "artists": "Gym Artist", "playlist": "Gym"}]}

    llm = LlmClient(complete_fn=fake_complete)
    result = SmartAssignService(repo, assignments, llm).run(batch_size=40)
    assert result.assigned == 1
    assert result.errors == []
    assert any("Pump — Gym Artist → Gym" in line for line in result.logs)


def test_smart_assign_skips_already_processed(repo) -> None:
    t1 = seed_track(repo, video_id="v1", title="Pump", artists="Gym Artist")
    t2 = seed_track(repo, video_id="v2", title="Later", artists="Other")
    seed_source_playlist(repo, track_ids=[t1, t2])
    assignments = AssignmentService(repo)
    assignments.create_destination("Gym")
    calls = {"n": 0}

    def fake_complete(system: str, user: str):
        calls["n"] += 1
        return {"assignments": [{"title": "Pump", "artists": "Gym Artist", "playlist": "Gym"}]}

    llm = LlmClient(complete_fn=fake_complete)
    service = SmartAssignService(repo, assignments, llm)
    first = service.run(batch_size=1)
    assert first.assigned == 1
    assert calls["n"] == 1
    second = service.run(batch_size=40)
    assert calls["n"] == 2
    assert second.processed == 1
    others = next(d for d in repo.list_destinations() if d.name == "Others")
    later = repo.get_track_by_video_id("v2")
    assert others.id in repo.get_assignment_destination_ids(int(later["id"]))
    third = service.run(batch_size=40)
    assert calls["n"] == 2
    assert third.processed == 0


def test_missing_category_creates_playlist(repo) -> None:
    tid = seed_track(repo, title="Qawwali Night", artists="Nusrat")
    seed_source_playlist(repo, track_ids=[tid])
    assignments = AssignmentService(repo)
    assignments.create_destination("Gym")

    def fake_complete(system: str, user: str):
        return {
            "assignments": [
                {"title": "Qawwali Night", "artists": "Nusrat", "playlists": ["Sufi"]}
            ]
        }

    result = SmartAssignService(repo, assignments, LlmClient(complete_fn=fake_complete)).run()
    assert result.assigned == 1
    assert "Sufi" in result.created_playlists
    dest = next(d for d in repo.list_destinations() if d.name == "Sufi")
    track = repo.assignable_tracks()[0]
    assert dest.id in repo.get_assignment_destination_ids(int(track["id"]))


def test_smart_assign_only_uses_selected_source_playlists(repo) -> None:
    music = seed_track(repo, video_id="m1", title="Pump", artists="Gym Artist")
    video = seed_track(repo, video_id="yt1", title="Talk", artists="Channel")
    both = seed_track(repo, video_id="b1", title="Shared", artists="Artist")
    seed_source_playlist(
        repo, playlist_id="PLmusic", title="Gym mix", track_ids=[music, both], include_in_smart_assign=True
    )
    seed_source_playlist(
        repo, playlist_id="PLyt", title="YouTube videos", track_ids=[video, both], include_in_smart_assign=False
    )

    pending = {r["title"] for r in repo.pending_smart_assign()}
    assert pending == {"Pump", "Shared"}
    assert repo.count_pending_smart_assign() == 2

    repo.set_source_playlist_smart_assign(
        next(p["id"] for p in repo.list_source_playlists() if p["title"] == "YouTube videos"),
        True,
    )
    assert repo.count_pending_smart_assign() == 3
