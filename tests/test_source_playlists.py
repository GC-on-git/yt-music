from __future__ import annotations

from datetime import datetime, timedelta

from src.ui.source_playlists import filter_source_playlists, normalize_privacy
from tests.conftest import seed_source_playlist


def test_normalize_privacy() -> None:
    assert normalize_privacy("public") == "Public"
    assert normalize_privacy("PRIVATE") == "Private"
    assert normalize_privacy("unlisted") == "Unlisted"
    assert normalize_privacy(None) == "Unknown"
    assert normalize_privacy("") == "Unknown"


def test_filter_source_playlists_by_privacy_search_and_import(repo) -> None:
    gym = seed_source_playlist(repo, playlist_id="PLgym", title="Gym mix")
    videos = seed_source_playlist(repo, playlist_id="PLyt", title="YouTube videos")
    drafts = seed_source_playlist(repo, playlist_id="PLdraft", title="Draft private")
    repo.upsert_source_playlist(
        playlist_id="PLgym", title="Gym mix", url=None, privacy="public", import_status="success"
    )
    repo.upsert_source_playlist(
        playlist_id="PLyt", title="YouTube videos", url=None, privacy="public", import_status="success"
    )
    repo.upsert_source_playlist(
        playlist_id="PLdraft", title="Draft private", url=None, privacy="private", import_status="success"
    )
    now = datetime(2026, 10, 25, 12, 0, 0)
    repo.conn.execute(
        "UPDATE source_playlists SET last_import_at = ? WHERE id = ?",
        ((now - timedelta(days=2)).isoformat(sep=" "), gym),
    )
    repo.conn.execute(
        "UPDATE source_playlists SET last_import_at = ? WHERE id = ?",
        ((now - timedelta(days=20)).isoformat(sep=" "), videos),
    )
    repo.conn.execute(
        "UPDATE source_playlists SET last_import_at = NULL WHERE id = ?",
        (drafts,),
    )
    repo.conn.commit()
    rows = repo.list_source_playlists()

    private_only = filter_source_playlists(rows, privacies=["Private"], now=now)
    assert [row["title"] for row in private_only] == ["Draft private"]

    searched = filter_source_playlists(rows, search="youtube", now=now)
    assert [row["title"] for row in searched] == ["YouTube videos"]

    recent = filter_source_playlists(rows, imported="Last 7 days", now=now)
    assert [row["title"] for row in recent] == ["Gym mix"]

    never = filter_source_playlists(rows, imported="Never imported", now=now)
    assert [row["title"] for row in never] == ["Draft private"]


def test_set_source_playlists_smart_assign_batch(repo) -> None:
    first = seed_source_playlist(repo, playlist_id="PL1", title="One", include_in_smart_assign=False)
    second = seed_source_playlist(repo, playlist_id="PL2", title="Two", include_in_smart_assign=False)
    repo.set_source_playlists_smart_assign([first, second], True)
    selected = {row["title"] for row in repo.list_source_playlists() if row["include_in_smart_assign"]}
    assert selected == {"One", "Two"}
    repo.set_source_playlists_smart_assign([first], False)
    selected = {row["title"] for row in repo.list_source_playlists() if row["include_in_smart_assign"]}
    assert selected == {"Two"}
