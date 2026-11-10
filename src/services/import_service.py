"""Idempotent playlist import into SQLite."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Callable

from src.db.repository import Repository
from src.db.track_identity import track_identity_key
from src.integrations.base import YouTubeMusicClient
from src.integrations.music_scope import (
    is_non_music_system_playlist,
    is_youtube_music_playlist_ref,
    should_import_track,
)
from src.integrations.playlist_url import extract_playlist_id
from src.integrations.ytmusic_adapter import AuthenticationUnavailableError
from src.logging_config import get_logger, safe_error_message
from src.models.domain import ImportStatus, SourcePlaylistInfo

logger = get_logger(__name__)

ProgressFn = Callable[[str], None]
ContinueFn = Callable[[], bool]


@dataclass
class PlaylistImportResult:
    playlist_id: str
    title: str
    status: str
    tracks_imported: int = 0
    error: str | None = None


@dataclass
class ImportSummary:
    run_id: int
    mode: str
    status: str
    playlists: list[PlaylistImportResult] = field(default_factory=list)
    tracks_seen: int = 0
    unique_tracks_upserted: int = 0
    skipped_playlists: int = 0
    skipped_tracks: int = 0

    @property
    def succeeded(self) -> int:
        return sum(1 for p in self.playlists if p.status == ImportStatus.SUCCESS.value)

    @property
    def failed(self) -> int:
        return sum(1 for p in self.playlists if p.status == ImportStatus.FAILED.value)

    @property
    def is_complete(self) -> bool:
        return self.failed == 0 and self.status == ImportStatus.SUCCESS.value


class ImportService:
    def __init__(self, repo: Repository, client: YouTubeMusicClient) -> None:
        self.repo = repo
        self.client = client

    def import_library(
        self,
        progress: ProgressFn | None = None,
        should_continue: ContinueFn | None = None,
    ) -> ImportSummary:
        def report(msg: str) -> None:
            logger.info(msg)
            if progress:
                progress(msg)

        run_id = self.repo.create_import_run("library")
        results: list[PlaylistImportResult] = []
        tracks_seen = 0
        unique_upserted = 0

        try:
            report("Listing library playlists…")
            upload_ids = self.client.upload_playlist_ids()
            playlists = [
                pl
                for pl in self.client.list_library_playlists()
                if not is_non_music_system_playlist(pl.playlist_id, pl.title)
                and pl.playlist_id not in upload_ids
                and pl.playlist_id.removeprefix("VL") not in upload_ids
            ]
        except AuthenticationUnavailableError as exc:
            summary = ImportSummary(
                run_id=run_id,
                mode="library",
                status=ImportStatus.FAILED.value,
                playlists=[],
                tracks_seen=0,
                unique_tracks_upserted=0,
            )
            self.repo.finish_import_run(
                run_id,
                status=ImportStatus.FAILED.value,
                playlists_total=0,
                playlists_succeeded=0,
                playlists_failed=1,
                tracks_seen=0,
                unique_tracks_upserted=0,
                error_summary=json.dumps([str(exc)]),
            )
            results.append(
                PlaylistImportResult(
                    playlist_id="*",
                    title="Library listing",
                    status=ImportStatus.FAILED.value,
                    error=str(exc),
                )
            )
            summary.playlists = results
            return summary
        except Exception as exc:  # noqa: BLE001
            err = safe_error_message(exc)
            self.repo.finish_import_run(
                run_id,
                status=ImportStatus.FAILED.value,
                playlists_total=0,
                playlists_succeeded=0,
                playlists_failed=1,
                tracks_seen=0,
                unique_tracks_upserted=0,
                error_summary=json.dumps([err]),
            )
            return ImportSummary(
                run_id=run_id,
                mode="library",
                status=ImportStatus.FAILED.value,
                playlists=[
                    PlaylistImportResult("*", "Library listing", ImportStatus.FAILED.value, error=err)
                ],
            )

        done_ids = self.repo.successfully_imported_playlist_ids()
        remaining = [pl for pl in playlists if pl.playlist_id not in done_ids]
        skipped_playlists = len(playlists) - len(remaining)
        if skipped_playlists:
            report(f"Skipping {skipped_playlists} already imported playlists.")
        if remaining:
            report(f"Resuming at '{remaining[0].title}' ({len(remaining)} remaining).")
        else:
            report("All playlists already imported.")

        skipped_tracks = 0
        for idx, pl in enumerate(remaining, start=1):
            if should_continue and not should_continue():
                report("Stopped.")
                break
            report(f"[{idx}/{len(remaining)}] {pl.title}")
            result, seen, upserted, skipped = self._import_one(
                pl.playlist_id, run_id, progress, resume=True, known=pl
            )
            results.append(result)
            tracks_seen += seen
            unique_upserted += upserted
            skipped_tracks += skipped

        summary = self._finalize(run_id, "library", results, tracks_seen, unique_upserted)
        summary.skipped_playlists = skipped_playlists
        summary.skipped_tracks = skipped_tracks
        return summary

    def import_playlist_ref(
        self, playlist_ref: str, progress: ProgressFn | None = None
    ) -> ImportSummary:
        if not is_youtube_music_playlist_ref(playlist_ref):
            raise ValueError(
                "Use a music.youtube.com playlist link or a raw playlist ID. "
                "Regular youtube.com playlists are not imported."
            )
        playlist_id = extract_playlist_id(playlist_ref)
        if not playlist_id:
            raise ValueError(
                "Could not parse a playlist ID from the given URL/ID. "
                "Paste a music.youtube.com playlist link or a playlist ID."
            )
        if is_non_music_system_playlist(playlist_id):
            raise ValueError(
                "That playlist is a YouTube system list, not a YouTube Music playlist."
            )
        run_id = self.repo.create_import_run("single")
        result, seen, upserted, _skipped = self._import_one(playlist_id, run_id, progress, resume=False)
        return self._finalize(run_id, "single", [result], seen, upserted)

    def retry_failed_playlists(
        self,
        progress: ProgressFn | None = None,
        should_continue: ContinueFn | None = None,
    ) -> ImportSummary:
        failed = [
            row
            for row in self.repo.list_source_playlists()
            if row["import_status"] in {ImportStatus.FAILED.value, ImportStatus.PARTIAL.value}
        ]
        run_id = self.repo.create_import_run("retry")
        results: list[PlaylistImportResult] = []
        tracks_seen = 0
        unique_upserted = 0
        for row in failed:
            if should_continue and not should_continue():
                if progress:
                    progress("Stopped.")
                break
            if progress:
                progress(f"Retrying {row['title']}…")
            result, seen, upserted, _skipped = self._import_one(
                row["playlist_id"], run_id, progress, resume=True
            )
            results.append(result)
            tracks_seen += seen
            unique_upserted += upserted
        if not failed:
            self.repo.finish_import_run(
                run_id,
                status=ImportStatus.SUCCESS.value,
                playlists_total=0,
                playlists_succeeded=0,
                playlists_failed=0,
                tracks_seen=0,
                unique_tracks_upserted=0,
                error_summary=None,
            )
            return ImportSummary(run_id, "retry", ImportStatus.SUCCESS.value)
        return self._finalize(run_id, "retry", results, tracks_seen, unique_upserted)

    def _import_one(
        self,
        playlist_id: str,
        run_id: int,
        progress: ProgressFn | None,
        *,
        resume: bool = True,
        known: SourcePlaylistInfo | None = None,
    ) -> tuple[PlaylistImportResult, int, int, int]:
        try:
            info, tracks = self.client.get_playlist(
                playlist_id, progress_callback=progress, known=known
            )
            local_id = self.repo.upsert_source_playlist(
                playlist_id=info.playlist_id,
                title=info.title,
                url=info.url,
                privacy=info.privacy,
                description=info.description,
                owned=info.owned,
                track_count_remote=info.track_count_remote,
                import_status=ImportStatus.PENDING.value,
            )
            existing_videos: set[str] = set()
            existing_positions: set[int] = set()
            existing_identities: set[tuple[str, str]] = set()
            if resume:
                existing_videos = self.repo.playlist_imported_video_ids(local_id)
                existing_positions = self.repo.playlist_imported_positions(local_id)
                existing_identities = self.repo.playlist_imported_identity_keys(local_id)
            else:
                self.repo.clear_playlist_items(local_id)

            upserted = 0
            seen = 0
            skipped = 0
            own_channels = self.client.own_channel_ids()
            for track in tracks:
                is_own = bool(track.is_own_upload or (track.channel_id and track.channel_id in own_channels))
                if is_own:
                    skipped += 1
                    continue
                if not should_import_track(track):
                    skipped += 1
                    continue
                artists = ", ".join(track.artists)
                identity = track_identity_key(track.title, artists)
                if track.video_id and track.video_id in existing_videos:
                    skipped += 1
                    continue
                if identity in existing_identities:
                    skipped += 1
                    continue
                if not track.video_id and track.position in existing_positions:
                    skipped += 1
                    continue
                seen += 1
                track_id = self.repo.upsert_track(
                    video_id=track.video_id,
                    title=track.title,
                    artists=artists,
                    album=track.album,
                    duration_seconds=track.duration_seconds,
                    duration_text=track.duration_text,
                    canonical_url=track.canonical_url,
                    thumbnail_url=track.thumbnail_url,
                    availability=track.availability.value,
                    needs_review=track.needs_review,
                    review_reason=track.review_reason,
                    channel_id=track.channel_id,
                    channel_title=track.channel_title,
                    is_own_upload=False,
                )
                if self.repo.playlist_contains_track(local_id, track_id):
                    skipped += 1
                    existing_identities.add(identity)
                    if track.video_id:
                        existing_videos.add(track.video_id)
                    continue
                upserted += 1
                self.repo.insert_playlist_item(
                    track_id=track_id,
                    source_playlist_id=local_id,
                    position=track.position,
                    set_video_id=track.set_video_id,
                    import_run_id=run_id,
                    availability=track.availability.value,
                    raw_title=track.title,
                )
                if not track.video_id:
                    self.repo.insert_ambiguous(
                        title=track.title,
                        artists=artists,
                        album=track.album,
                        source_playlist_id=local_id,
                        position=track.position,
                        reason=track.review_reason or "missing_video_id",
                        raw_json=json.dumps(
                            {k: track.raw.get(k) for k in ("title", "artists", "album", "videoId")}
                        ),
                    )
                if track.video_id:
                    existing_videos.add(track.video_id)
                existing_identities.add(identity)
                existing_positions.add(track.position)
                if seen % 25 == 0:
                    self.repo.mark_source_playlist_imported(local_id, ImportStatus.PARTIAL.value)
                    self.repo.conn.commit()

            self.repo.mark_source_playlist_imported(local_id, ImportStatus.SUCCESS.value)
            self.repo.conn.commit()
            return (
                PlaylistImportResult(
                    playlist_id=info.playlist_id,
                    title=info.title,
                    status=ImportStatus.SUCCESS.value,
                    tracks_imported=seen,
                ),
                seen,
                upserted,
                skipped,
            )
        except Exception as exc:  # noqa: BLE001
            err = safe_error_message(exc)
            logger.error("Playlist import failed for %s: %s", playlist_id, err)
            existing = self.repo.get_source_playlist_by_remote_id(playlist_id)
            if existing:
                status = (
                    ImportStatus.PARTIAL.value
                    if self.repo.playlist_imported_positions(int(existing["id"]))
                    else ImportStatus.FAILED.value
                )
                self.repo.mark_source_playlist_imported(int(existing["id"]), status, err)
            else:
                local_id = self.repo.upsert_source_playlist(
                    playlist_id=playlist_id,
                    title=playlist_id,
                    url=f"https://music.youtube.com/playlist?list={playlist_id}",
                    import_status=ImportStatus.FAILED.value,
                    last_error=err,
                )
                self.repo.mark_source_playlist_imported(local_id, ImportStatus.FAILED.value, err)
            self.repo.conn.commit()
            return (
                PlaylistImportResult(
                    playlist_id=playlist_id,
                    title=existing["title"] if existing else playlist_id,
                    status=ImportStatus.FAILED.value,
                    error=err,
                ),
                0,
                0,
                0,
            )

    def _finalize(
        self,
        run_id: int,
        mode: str,
        results: list[PlaylistImportResult],
        tracks_seen: int,
        unique_upserted: int,
    ) -> ImportSummary:
        failed = [r for r in results if r.status == ImportStatus.FAILED.value]
        succeeded = [r for r in results if r.status == ImportStatus.SUCCESS.value]
        if failed and succeeded:
            status = ImportStatus.PARTIAL.value
        elif failed and not succeeded:
            status = ImportStatus.FAILED.value
        else:
            status = ImportStatus.SUCCESS.value

        errors = [f"{r.title}: {r.error}" for r in failed if r.error]
        self.repo.finish_import_run(
            run_id,
            status=status,
            playlists_total=len(results),
            playlists_succeeded=len(succeeded),
            playlists_failed=len(failed),
            tracks_seen=tracks_seen,
            unique_tracks_upserted=unique_upserted,
            error_summary=json.dumps(errors) if errors else None,
        )
        self.repo.conn.commit()
        return ImportSummary(
            run_id=run_id,
            mode=mode,
            status=status,
            playlists=results,
            tracks_seen=tracks_seen,
            unique_tracks_upserted=unique_upserted,
        )

