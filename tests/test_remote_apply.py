"""Remote apply with a fake YouTube Music client."""

from __future__ import annotations

from typing import Any

from src.models.domain import RemoteTrack, SourcePlaylistInfo
from src.services.assignment_service import AssignmentService
from src.services.remote_apply_service import RemoteApplyService
from tests.conftest import seed_track


class FakeClient:
    def __init__(self, *, authenticated: bool = True, fail_add: bool = False) -> None:
        self._authenticated = authenticated
        self.fail_add = fail_add
        self.created: list[str] = []
        self.adds: list[tuple[str, list[str]]] = []
        self._playlist_tracks: dict[str, list[str]] = {}
        self._next_id = 1

    def is_authenticated(self) -> bool:
        return self._authenticated

    def auth_status_message(self) -> str:
        return "ok" if self._authenticated else "not auth"

    def list_library_playlists(self) -> list[SourcePlaylistInfo]:
        return []

    def get_playlist(
        self,
        playlist_id: str,
        *,
        progress_callback: Any | None = None,
        known: SourcePlaylistInfo | None = None,
    ) -> tuple[SourcePlaylistInfo, list[RemoteTrack]]:
        raise NotImplementedError

    def create_playlist(self, title: str, description: str = "") -> str:
        pid = f"PL{self._next_id}"
        self._next_id += 1
        self.created.append(title)
        self._playlist_tracks[pid] = []
        return pid

    def add_tracks_to_playlist(self, playlist_id: str, video_ids: list[str]) -> dict[str, Any]:
        if self.fail_add:
            raise RuntimeError("network boom")
        self.adds.append((playlist_id, list(video_ids)))
        self._playlist_tracks.setdefault(playlist_id, []).extend(video_ids)
        return {"status": "ok"}

    def get_playlist_track_ids(self, playlist_id: str) -> list[str]:
        return list(self._playlist_tracks.get(playlist_id, []))

    def supports_remote_writes(self) -> bool:
        return self._authenticated

    def own_channel_ids(self) -> set[str]:
        return set()

    def upload_playlist_ids(self) -> set[str]:
        return set()


def _prepare(repo) -> tuple[RemoteApplyService, FakeClient, int]:
    track_id = seed_track(repo, video_id="abc123", title="Track")
    assignments = AssignmentService(repo)
    dest_id = assignments.create_destination("Gym")
    assignments.assign(track_id, dest_id)
    client = FakeClient()
    return RemoteApplyService(repo, client), client, dest_id


def test_preview_includes_create_and_add(repo) -> None:
    service, _, _ = _prepare(repo)
    ops = service.preview()
    types = {o.operation_type.value for o in ops}
    assert "create_playlist" in types
    assert "add_track" in types


def test_apply_requires_confirmation(repo) -> None:
    service, client, _ = _prepare(repo)
    result = service.apply(confirmed=False)
    assert result.errors
    assert not client.created


def test_apply_creates_playlist_and_adds_tracks(repo) -> None:
    service, client, dest_id = _prepare(repo)
    result = service.apply(confirmed=True)
    assert result.failed == 0
    assert result.succeeded >= 2
    assert client.created == ["Gym"]
    assert any(vids == ["abc123"] for _, vids in client.adds)

    dest = next(d for d in repo.list_destinations() if d.id == dest_id)
    assert dest.remote_playlist_id

    # Idempotent second apply
    again = service.apply(confirmed=True)
    assert again.skipped >= 1
    assert len(client.created) == 1


def test_apply_without_auth(repo) -> None:
    track_id = seed_track(repo)
    assignments = AssignmentService(repo)
    dest_id = assignments.create_destination("X")
    assignments.assign(track_id, dest_id)
    client = FakeClient(authenticated=False)
    service = RemoteApplyService(repo, client)
    result = service.apply(confirmed=True)
    assert result.remote_writes_available is False
    assert result.errors


def test_retry_failed_only_skips_unattempted(repo) -> None:
    service, client, _ = _prepare(repo)
    result = service.apply(confirmed=True, retry_failed_only=True)
    assert not client.created
    assert result.skipped >= 1


def test_retry_failed_add(repo) -> None:
    track_id = seed_track(repo, video_id="failvid", title="Boom")
    assignments = AssignmentService(repo)
    dest_id = assignments.create_destination("RetryDest")
    assignments.assign(track_id, dest_id)

    client = FakeClient(fail_add=True)
    service = RemoteApplyService(repo, client)
    first = service.apply(confirmed=True)
    assert first.failed >= 1
    assert client.created  # playlist create succeeded

    client.fail_add = False
    second = service.apply(confirmed=True, retry_failed_only=True)
    assert second.failed == 0
    assert any("failvid" in vids for _, vids in client.adds)
