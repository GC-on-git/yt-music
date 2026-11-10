"""Review-first, non-destructive remote playlist population."""

from __future__ import annotations

from dataclasses import dataclass, field
from collections.abc import Callable
from typing import Any

from src.db.repository import Repository
from src.integrations.base import YouTubeMusicClient
from src.logging_config import get_logger, safe_error_message
from src.models.domain import OperationStatus, OperationType, RemoteOperationPreview

logger = get_logger(__name__)


@dataclass
class ApplyResult:
    previews: list[RemoteOperationPreview] = field(default_factory=list)
    executed: int = 0
    succeeded: int = 0
    failed: int = 0
    skipped: int = 0
    errors: list[str] = field(default_factory=list)
    remote_writes_available: bool = True
    messages: list[str] = field(default_factory=list)


class RemoteApplyService:
    """Creates/populates destination playlists only. Never mutates source playlists."""

    def __init__(self, repo: Repository, client: YouTubeMusicClient) -> None:
        self.repo = repo
        self.client = client

    def preview(self) -> list[RemoteOperationPreview]:
        ops: list[RemoteOperationPreview] = []
        for dest in self.repo.list_destinations():
            tracks = self.repo.destination_tracks(dest.id)
            video_tracks = [t for t in tracks if t["video_id"]]
            if not dest.remote_playlist_id:
                ops.append(
                    RemoteOperationPreview(
                        operation_type=OperationType.CREATE_PLAYLIST,
                        destination_local_id=dest.id,
                        destination_name=dest.name,
                        details={"track_count": len(video_tracks)},
                    )
                )
            for track in video_tracks:
                ops.append(
                    RemoteOperationPreview(
                        operation_type=OperationType.ADD_TRACK,
                        destination_local_id=dest.id,
                        destination_name=dest.name,
                        video_id=track["video_id"],
                        track_title=track["title"],
                        remote_playlist_id=dest.remote_playlist_id,
                    )
                )
        return ops

    def apply(
        self,
        *,
        confirmed: bool,
        retry_failed_only: bool = False,
        should_continue: Callable[[], bool] | None = None,
        progress: Callable[[str], None] | None = None,
    ) -> ApplyResult:
        result = ApplyResult(remote_writes_available=self.client.supports_remote_writes())
        if not confirmed:
            result.errors.append("Confirmation required before remote changes.")
            return result
        if not self.client.supports_remote_writes():
            result.remote_writes_available = False
            result.errors.append(
                "Remote writes unavailable (not authenticated). "
                "Your local plan is preserved — export CSV/JSON instead."
            )
            result.previews = self.preview()
            return result

        result.previews = self.preview()
        for dest in self.repo.list_destinations():
            if should_continue and not should_continue():
                if progress:
                    progress("Stopped.")
                break
            if progress:
                progress(f"Publishing {dest.name}…")
            self._apply_destination(dest.id, dest.name, dest.remote_playlist_id, result, retry_failed_only)
        return result

    def _apply_destination(
        self,
        dest_id: int,
        dest_name: str,
        remote_playlist_id: str | None,
        result: ApplyResult,
        retry_failed_only: bool,
    ) -> None:
        create_key = f"create_playlist:{dest_id}"
        playlist_id = remote_playlist_id

        if not playlist_id:
            if self.repo.operation_succeeded(create_key):
                # Recover remote id from last success log if DB column empty
                logs = self.repo.list_operations(limit=500)
                for op in logs:
                    if (
                        op["idempotency_key"] == create_key
                        and op["status"] == OperationStatus.SUCCESS.value
                        and op["remote_playlist_id"]
                    ):
                        playlist_id = op["remote_playlist_id"]
                        self.repo.set_destination_remote_id(dest_id, playlist_id)
                        break

        create_fail_key = f"{create_key}:attempt"
        if not playlist_id:
            if self.repo.operation_succeeded(create_key):
                result.skipped += 1
            elif retry_failed_only and not self.repo.operation_failed(create_fail_key):
                result.skipped += 1
                result.messages.append(
                    f"Skipped create for '{dest_name}' (retry-failed-only; no prior failure)."
                )
                self.repo.conn.commit()
                return
            else:
                result.executed += 1
                try:
                    playlist_id = self.client.create_playlist(
                        dest_name, f"Created by YT Music Organizer for '{dest_name}'"
                    )
                    self.repo.set_destination_remote_id(dest_id, playlist_id)
                    self.repo.log_operation(
                        operation_type=OperationType.CREATE_PLAYLIST.value,
                        status=OperationStatus.SUCCESS.value,
                        destination_playlist_id=dest_id,
                        remote_playlist_id=playlist_id,
                        message=f"Created remote playlist {playlist_id}",
                        idempotency_key=create_key,
                    )
                    result.succeeded += 1
                    result.messages.append(f"Created playlist '{dest_name}' → {playlist_id}")
                except Exception as exc:  # noqa: BLE001
                    err = safe_error_message(exc)
                    self.repo.log_operation(
                        operation_type=OperationType.CREATE_PLAYLIST.value,
                        status=OperationStatus.FAILED.value,
                        destination_playlist_id=dest_id,
                        message=err,
                        idempotency_key=create_fail_key,
                    )
                    result.failed += 1
                    result.errors.append(f"Create '{dest_name}': {err}")
                    self.repo.conn.commit()
                    return

        if not playlist_id:
            result.errors.append(f"No remote playlist id for '{dest_name}' — cannot add tracks.")
            self.repo.conn.commit()
            return

        tracks = [t for t in self.repo.destination_tracks(dest_id) if t["video_id"]]
        for track in tracks:
            key = f"add_track:{dest_id}:{track['video_id']}"
            fail_key = f"{key}:fail"
            if self.repo.operation_succeeded(key):
                result.skipped += 1
                continue
            if retry_failed_only and not self.repo.operation_failed(fail_key):
                result.skipped += 1
                continue
            result.executed += 1
            try:
                self.client.add_tracks_to_playlist(playlist_id, [track["video_id"]])
                self.repo.log_operation(
                    operation_type=OperationType.ADD_TRACK.value,
                    status=OperationStatus.SUCCESS.value,
                    destination_playlist_id=dest_id,
                    track_id=int(track["id"]),
                    video_id=track["video_id"],
                    remote_playlist_id=playlist_id,
                    message=f"Added {track['title']}",
                    idempotency_key=key,
                )
                result.succeeded += 1
            except Exception as exc:  # noqa: BLE001
                err = safe_error_message(exc)
                # Duplicate on remote is treated as success for idempotency
                if "duplicate" in err.lower() or "already" in err.lower():
                    self.repo.log_operation(
                        operation_type=OperationType.ADD_TRACK.value,
                        status=OperationStatus.SUCCESS.value,
                        destination_playlist_id=dest_id,
                        track_id=int(track["id"]),
                        video_id=track["video_id"],
                        remote_playlist_id=playlist_id,
                        message=f"Already present: {track['title']}",
                        idempotency_key=key,
                    )
                    result.succeeded += 1
                    result.skipped += 1
                else:
                    self.repo.log_operation(
                        operation_type=OperationType.ADD_TRACK.value,
                        status=OperationStatus.FAILED.value,
                        destination_playlist_id=dest_id,
                        track_id=int(track["id"]),
                        video_id=track["video_id"],
                        remote_playlist_id=playlist_id,
                        message=err,
                        idempotency_key=f"{key}:fail",
                    )
                    result.failed += 1
                    result.errors.append(f"Add '{track['title']}' to '{dest_name}': {err}")

        # Best-effort verification
        if playlist_id:
            try:
                remote_ids = set(self.client.get_playlist_track_ids(playlist_id))
                expected = {t["video_id"] for t in tracks}
                missing = expected - remote_ids
                self.repo.log_operation(
                    operation_type=OperationType.VERIFY_PLAYLIST.value,
                    status=(
                        OperationStatus.SUCCESS.value
                        if not missing
                        else OperationStatus.FAILED.value
                    ),
                    destination_playlist_id=dest_id,
                    remote_playlist_id=playlist_id,
                    message=(
                        "Verified all tracks present"
                        if not missing
                        else f"Missing {len(missing)} track(s) after apply"
                    ),
                    idempotency_key=f"verify:{dest_id}:{playlist_id}",
                    details={"missing": sorted(missing)},
                )
                if missing:
                    result.messages.append(
                        f"Verify '{dest_name}': {len(missing)} track(s) not yet visible remotely."
                    )
            except Exception as exc:  # noqa: BLE001
                result.messages.append(
                    f"Could not verify '{dest_name}': {safe_error_message(exc)}"
                )

        self.repo.conn.commit()

    def safety_guarantees(self) -> list[str]:
        return [
            "Source playlists are never deleted, emptied, or modified.",
            "Tracks are only added to new/destination playlists.",
            "Each remote operation is logged and idempotent via keys.",
            "Failed operations can be retried without duplicating successes.",
        ]
