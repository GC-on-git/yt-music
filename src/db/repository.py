"""Data access layer for the organizer database."""

from __future__ import annotations

import json
import sqlite3
from typing import Any, Iterable, Sequence

from src.db.connection import execute, fetchall, fetchone, transaction
from src.db.track_identity import track_identity_key
from src.models.domain import DashboardStats, DestinationPlaylist, ImportRunSummary
from src.models.state_machines import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES

_SMART_PENDING_WHERE = """
    COALESCE(t.is_own_upload, 0) = 0
    AND COALESCE(t.smart_assigned, 0) = 0
    AND NOT EXISTS (
        SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id
    )
    AND EXISTS (
        SELECT 1 FROM playlist_items pi
        JOIN source_playlists sp ON sp.id = pi.source_playlist_id
        WHERE pi.track_id = t.id
          AND COALESCE(sp.include_in_smart_assign, 0) = 1
    )
"""


class Repository:
    def __init__(self, conn: sqlite3.Connection) -> None:
        self.conn = conn

    # ---- tracks ----
    def upsert_track(
        self,
        *,
        video_id: str | None,
        title: str,
        artists: str,
        album: str | None,
        duration_seconds: int | None,
        duration_text: str | None,
        canonical_url: str | None,
        thumbnail_url: str | None,
        availability: str,
        needs_review: bool = False,
        review_reason: str | None = None,
        channel_id: str | None = None,
        channel_title: str | None = None,
        is_own_upload: bool = False,
    ) -> int:
        existing = self.find_track(video_id=video_id, title=title, artists=artists)
        if existing:
            fill_video_id = None
            if video_id and not existing["video_id"]:
                clash = fetchone(
                    self.conn,
                    "SELECT id FROM tracks WHERE video_id = ? AND id != ?",
                    (video_id, existing["id"]),
                )
                if clash is None:
                    fill_video_id = video_id
            execute(
                self.conn,
                """
                UPDATE tracks SET
                    video_id = COALESCE(video_id, ?),
                    title = ?, artists = ?, album = COALESCE(?, album),
                    duration_seconds = COALESCE(?, duration_seconds),
                    duration_text = COALESCE(?, duration_text),
                    canonical_url = COALESCE(canonical_url, ?),
                    thumbnail_url = COALESCE(thumbnail_url, ?),
                    availability = ?,
                    needs_review = CASE WHEN ? THEN 1 ELSE needs_review END,
                    review_reason = COALESCE(?, review_reason),
                    channel_id = COALESCE(?, channel_id),
                    channel_title = COALESCE(?, channel_title),
                    is_own_upload = CASE WHEN ? THEN 1 ELSE is_own_upload END,
                    last_seen_at = datetime('now')
                WHERE id = ?
                """,
                (
                    fill_video_id,
                    title.strip() or existing["title"],
                    (artists or "").strip() or existing["artists"],
                    album,
                    duration_seconds,
                    duration_text,
                    canonical_url,
                    thumbnail_url,
                    availability,
                    1 if needs_review else 0,
                    review_reason,
                    channel_id,
                    channel_title,
                    1 if is_own_upload else 0,
                    existing["id"],
                ),
            )
            return int(existing["id"])

        cur = execute(
            self.conn,
            """
            INSERT INTO tracks (
                video_id, title, artists, album, duration_seconds, duration_text,
                canonical_url, thumbnail_url, availability, needs_review, review_reason,
                channel_id, channel_title, is_own_upload
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                video_id,
                title.strip(),
                (artists or "").strip(),
                album,
                duration_seconds,
                duration_text,
                canonical_url,
                thumbnail_url,
                availability,
                1 if needs_review or not video_id else 0,
                review_reason or ("missing_video_id" if not video_id else None),
                channel_id,
                channel_title,
                1 if is_own_upload else 0,
            ),
        )
        return int(cur.lastrowid)

    def find_track(
        self,
        *,
        video_id: str | None = None,
        title: str | None = None,
        artists: str | None = None,
    ) -> sqlite3.Row | None:
        if video_id:
            row = fetchone(self.conn, "SELECT * FROM tracks WHERE video_id = ?", (video_id,))
            if row:
                return row
        title_key, artists_key = track_identity_key(title, artists)
        if not title_key:
            return None
        return fetchone(
            self.conn,
            """
            SELECT * FROM tracks
            WHERE lower(trim(title)) = ? AND lower(trim(artists)) = ?
            ORDER BY
                CASE WHEN video_id IS NULL OR video_id = '' THEN 1 ELSE 0 END,
                id ASC
            LIMIT 1
            """,
            (title_key, artists_key),
        )

    def get_track(self, track_id: int) -> sqlite3.Row | None:
        return fetchone(self.conn, "SELECT * FROM tracks WHERE id = ?", (track_id,))

    def get_track_by_video_id(self, video_id: str) -> sqlite3.Row | None:
        return fetchone(self.conn, "SELECT * FROM tracks WHERE video_id = ?", (video_id,))

    def playlist_contains_track(self, source_playlist_local_id: int, track_id: int) -> bool:
        row = fetchone(
            self.conn,
            """
            SELECT 1 AS ok FROM playlist_items
            WHERE source_playlist_id = ? AND track_id = ?
            LIMIT 1
            """,
            (source_playlist_local_id, track_id),
        )
        return row is not None

    def playlist_imported_identity_keys(self, source_playlist_local_id: int) -> set[tuple[str, str]]:
        rows = fetchall(
            self.conn,
            """
            SELECT t.title, t.artists
            FROM playlist_items pi
            JOIN tracks t ON t.id = pi.track_id
            WHERE pi.source_playlist_id = ?
            """,
            (source_playlist_local_id,),
        )
        return {track_identity_key(r["title"], r["artists"]) for r in rows}

    def assignable_tracks(self, *, search: str | None = None, limit: int = 500) -> list[sqlite3.Row]:
        where = ["COALESCE(is_own_upload, 0) = 0"]
        params: list[Any] = []
        if search and search.strip():
            where.append("(title LIKE ? OR artists LIKE ?)")
            like = f"%{search.strip()}%"
            params.extend([like, like])
        return fetchall(
            self.conn,
            f"""
            SELECT * FROM tracks
            WHERE {' AND '.join(where)}
            ORDER BY title COLLATE NOCASE
            LIMIT ?
            """,
            [*params, limit],
        )

    def pending_smart_assign(self, *, limit: int | None = None) -> list[sqlite3.Row]:
        sql = f"""
            SELECT t.* FROM tracks t
            WHERE {_SMART_PENDING_WHERE}
            ORDER BY t.id ASC
        """
        params: list[Any] = []
        if limit is not None:
            sql += " LIMIT ?"
            params.append(limit)
        return fetchall(self.conn, sql, params)

    def count_pending_smart_assign(self) -> int:
        row = fetchone(
            self.conn,
            f"SELECT COUNT(*) AS c FROM tracks t WHERE {_SMART_PENDING_WHERE}",
        )
        return int(row["c"]) if row else 0

    def count_smart_assigned(self) -> int:
        row = fetchone(
            self.conn,
            """
            SELECT COUNT(*) AS c FROM tracks
            WHERE COALESCE(is_own_upload, 0) = 0 AND COALESCE(smart_assigned, 0) = 1
            """,
        )
        return int(row["c"]) if row else 0

    def mark_smart_assigned(self, track_ids: Sequence[int]) -> None:
        if not track_ids:
            return
        placeholders = ",".join("?" for _ in track_ids)
        execute(
            self.conn,
            f"UPDATE tracks SET smart_assigned = 1 WHERE id IN ({placeholders})",
            list(track_ids),
        )
        self.conn.commit()

    def assigned_tracks_for_review(
        self,
        *,
        destination_id: int | None = None,
        unassigned_only: bool = False,
    ) -> list[sqlite3.Row]:
        where = ["COALESCE(t.is_own_upload, 0) = 0"]
        params: list[Any] = []
        order_sql = """
            CASE WHEN dest_sort IS NULL THEN 1 ELSE 0 END,
            dest_sort ASC,
            assign_pos ASC,
            t.id ASC
        """
        if unassigned_only:
            where.append(
                "NOT EXISTS (SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id)"
            )
            order_sql = "t.title COLLATE NOCASE, t.id ASC"
        elif destination_id is not None:
            dest_id = int(destination_id)
            where.append(
                """
                EXISTS (
                    SELECT 1 FROM track_assignments ta
                    WHERE ta.track_id = t.id AND ta.destination_playlist_id = ?
                )
                """
            )
            params.append(dest_id)
            order_sql = """
                COALESCE(
                    (
                        SELECT ta.position
                        FROM track_assignments ta
                        WHERE ta.track_id = t.id AND ta.destination_playlist_id = ?
                    ),
                    999999
                ) ASC,
                t.id ASC
            """
            params.append(dest_id)

        return fetchall(
            self.conn,
            f"""
            SELECT t.*,
                   (SELECT GROUP_CONCAT(dp.name, ' | ')
                    FROM track_assignments ta
                    JOIN destination_playlists dp ON dp.id = ta.destination_playlist_id
                    WHERE ta.track_id = t.id) AS destination_memberships,
                   (SELECT MIN(dp.sort_order)
                    FROM track_assignments ta
                    JOIN destination_playlists dp ON dp.id = ta.destination_playlist_id
                    WHERE ta.track_id = t.id) AS dest_sort,
                   (SELECT MIN(COALESCE(ta.position, 999999))
                    FROM track_assignments ta
                    WHERE ta.track_id = t.id) AS assign_pos
            FROM tracks t
            WHERE {' AND '.join(where)}
            ORDER BY {order_sql}
            """,
            params,
        )

    def destination_track_counts(self) -> dict[int, int]:
        rows = fetchall(
            self.conn,
            """
            SELECT ta.destination_playlist_id AS dest_id, COUNT(*) AS c
            FROM track_assignments ta
            JOIN tracks t ON t.id = ta.track_id
            WHERE COALESCE(t.is_own_upload, 0) = 0
            GROUP BY ta.destination_playlist_id
            """,
        )
        return {int(r["dest_id"]): int(r["c"]) for r in rows}

    def count_unassigned_tracks(self) -> int:
        row = fetchone(
            self.conn,
            """
            SELECT COUNT(*) AS c FROM tracks t
            WHERE COALESCE(t.is_own_upload, 0) = 0
              AND NOT EXISTS (
                SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id
              )
            """,
        )
        return int(row["c"]) if row else 0

    # ---- source playlists ----
    def upsert_source_playlist(
        self,
        *,
        playlist_id: str,
        title: str,
        url: str | None,
        privacy: str | None = None,
        description: str | None = None,
        owned: bool | None = None,
        track_count_remote: int | None = None,
        import_status: str = "pending",
        last_error: str | None = None,
    ) -> int:
        existing = fetchone(
            self.conn,
            "SELECT id FROM source_playlists WHERE playlist_id = ?",
            (playlist_id,),
        )
        if existing:
            execute(
                self.conn,
                """
                UPDATE source_playlists SET
                    title = ?, url = ?, privacy = ?, description = ?,
                    owned = ?, track_count_remote = ?,
                    import_status = ?, last_error = ?,
                    updated_at = datetime('now')
                WHERE id = ?
                """,
                (
                    title,
                    url,
                    privacy,
                    description,
                    None if owned is None else (1 if owned else 0),
                    track_count_remote,
                    import_status,
                    last_error,
                    existing["id"],
                ),
            )
            return int(existing["id"])
        cur = execute(
            self.conn,
            """
            INSERT INTO source_playlists (
                playlist_id, title, url, privacy, description, owned,
                track_count_remote, import_status, last_error
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                playlist_id,
                title,
                url,
                privacy,
                description,
                None if owned is None else (1 if owned else 0),
                track_count_remote,
                import_status,
                last_error,
            ),
        )
        return int(cur.lastrowid)

    def mark_source_playlist_imported(
        self, local_id: int, status: str, error: str | None = None
    ) -> None:
        execute(
            self.conn,
            """
            UPDATE source_playlists SET
                import_status = ?, last_error = ?, last_import_at = datetime('now'),
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, error, local_id),
        )

    def set_source_playlist_smart_assign(self, playlist_id: int, enabled: bool) -> None:
        execute(
            self.conn,
            """
            UPDATE source_playlists
            SET include_in_smart_assign = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (1 if enabled else 0, playlist_id),
        )
        self.conn.commit()

    def set_source_playlists_smart_assign(self, playlist_ids: Sequence[int], enabled: bool) -> None:
        ids = [int(item) for item in playlist_ids]
        if not ids:
            return
        placeholders = ", ".join("?" for _ in ids)
        execute(
            self.conn,
            f"""
            UPDATE source_playlists
            SET include_in_smart_assign = ?, updated_at = datetime('now')
            WHERE id IN ({placeholders})
            """,
            (1 if enabled else 0, *ids),
        )
        self.conn.commit()

    def set_all_source_playlists_smart_assign(self, enabled: bool) -> None:
        execute(
            self.conn,
            """
            UPDATE source_playlists
            SET include_in_smart_assign = ?, updated_at = datetime('now')
            """,
            (1 if enabled else 0,),
        )
        self.conn.commit()

    def selected_smart_assign_playlist_count(self) -> int:
        row = fetchone(
            self.conn,
            """
            SELECT COUNT(*) AS c FROM source_playlists
            WHERE COALESCE(include_in_smart_assign, 0) = 1
            """,
        )
        return int(row["c"]) if row else 0

    def list_source_playlists(self) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT sp.*,
                   (SELECT COUNT(*) FROM playlist_items pi WHERE pi.source_playlist_id = sp.id) AS local_track_count
            FROM source_playlists sp
            ORDER BY sp.title COLLATE NOCASE
            """,
        )

    def get_source_playlist_by_remote_id(self, playlist_id: str) -> sqlite3.Row | None:
        for candidate in _playlist_id_candidates(playlist_id):
            row = fetchone(
                self.conn,
                "SELECT * FROM source_playlists WHERE playlist_id = ?",
                (candidate,),
            )
            if row:
                return row
        return None

    def successfully_imported_playlist_ids(self) -> set[str]:
        rows = fetchall(
            self.conn,
            "SELECT playlist_id FROM source_playlists WHERE import_status = 'success'",
        )
        ids: set[str] = set()
        for row in rows:
            pid = str(row["playlist_id"])
            ids.add(pid)
            ids.add(pid.removeprefix("VL"))
            if not pid.startswith("VL"):
                ids.add(f"VL{pid}")
        return ids

    def playlist_imported_video_ids(self, source_playlist_local_id: int) -> set[str]:
        rows = fetchall(
            self.conn,
            """
            SELECT t.video_id
            FROM playlist_items pi
            JOIN tracks t ON t.id = pi.track_id
            WHERE pi.source_playlist_id = ? AND t.video_id IS NOT NULL
            """,
            (source_playlist_local_id,),
        )
        return {str(r["video_id"]) for r in rows}

    def playlist_imported_positions(self, source_playlist_local_id: int) -> set[int]:
        rows = fetchall(
            self.conn,
            "SELECT position FROM playlist_items WHERE source_playlist_id = ?",
            (source_playlist_local_id,),
        )
        return {int(r["position"]) for r in rows}

    def clear_playlist_items(self, source_playlist_local_id: int) -> None:
        execute(
            self.conn,
            "DELETE FROM playlist_items WHERE source_playlist_id = ?",
            (source_playlist_local_id,),
        )

    def insert_playlist_item(
        self,
        *,
        track_id: int,
        source_playlist_id: int,
        position: int,
        set_video_id: str | None,
        import_run_id: int | None,
        availability: str | None,
        raw_title: str | None,
    ) -> None:
        execute(
            self.conn,
            """
            INSERT OR IGNORE INTO playlist_items (
                track_id, source_playlist_id, position, set_video_id,
                import_run_id, availability, raw_title
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                track_id,
                source_playlist_id,
                position,
                set_video_id,
                import_run_id,
                availability,
                raw_title,
            ),
        )

    def list_playlist_items(self, source_playlist_local_id: int) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT pi.*, t.title, t.artists, t.album, t.duration_text, t.video_id,
                   t.canonical_url, t.availability AS track_availability, t.needs_review
            FROM playlist_items pi
            JOIN tracks t ON t.id = pi.track_id
            WHERE pi.source_playlist_id = ?
            ORDER BY pi.position ASC
            """,
            (source_playlist_local_id,),
        )

    # ---- import runs ----
    def create_import_run(self, mode: str) -> int:
        cur = execute(
            self.conn,
            "INSERT INTO import_runs(mode, status) VALUES (?, 'pending')",
            (mode,),
        )
        return int(cur.lastrowid)

    def finish_import_run(
        self,
        run_id: int,
        *,
        status: str,
        playlists_total: int,
        playlists_succeeded: int,
        playlists_failed: int,
        tracks_seen: int,
        unique_tracks_upserted: int,
        error_summary: str | None = None,
    ) -> None:
        execute(
            self.conn,
            """
            UPDATE import_runs SET
                finished_at = datetime('now'), status = ?,
                playlists_total = ?, playlists_succeeded = ?, playlists_failed = ?,
                tracks_seen = ?, unique_tracks_upserted = ?, error_summary = ?
            WHERE id = ?
            """,
            (
                status,
                playlists_total,
                playlists_succeeded,
                playlists_failed,
                tracks_seen,
                unique_tracks_upserted,
                error_summary,
                run_id,
            ),
        )

    def get_import_run(self, run_id: int) -> ImportRunSummary | None:
        row = fetchone(self.conn, "SELECT * FROM import_runs WHERE id = ?", (run_id,))
        if not row:
            return None
        errors = []
        if row["error_summary"]:
            try:
                errors = json.loads(row["error_summary"])
            except json.JSONDecodeError:
                errors = [row["error_summary"]]
        return ImportRunSummary(
            id=row["id"],
            started_at=row["started_at"],
            finished_at=row["finished_at"],
            mode=row["mode"],
            status=row["status"],
            playlists_total=row["playlists_total"],
            playlists_succeeded=row["playlists_succeeded"],
            playlists_failed=row["playlists_failed"],
            tracks_seen=row["tracks_seen"],
            unique_tracks_upserted=row["unique_tracks_upserted"],
            errors=errors,
        )

    def last_successful_import_at(self) -> str | None:
        row = fetchone(
            self.conn,
            """
            SELECT finished_at FROM import_runs
            WHERE status IN ('success', 'partial') AND finished_at IS NOT NULL
            ORDER BY finished_at DESC LIMIT 1
            """,
        )
        return row["finished_at"] if row else None

    # ---- destinations / assignments ----
    def create_destination(self, name: str, description: str | None = None) -> int:
        row = fetchone(
            self.conn, "SELECT COALESCE(MAX(sort_order), 0) + 1 AS n FROM destination_playlists"
        )
        sort_order = int(row["n"]) if row else 1
        cur = execute(
            self.conn,
            """
            INSERT INTO destination_playlists(name, description, sort_order)
            VALUES (?, ?, ?)
            """,
            (name.strip(), description, sort_order),
        )
        return int(cur.lastrowid)

    def get_destination_by_name(self, name: str) -> DestinationPlaylist | None:
        row = fetchone(
            self.conn,
            """
            SELECT * FROM destination_playlists
            WHERE lower(trim(name)) = lower(trim(?))
            LIMIT 1
            """,
            (name.strip(),),
        )
        if not row:
            return None
        return DestinationPlaylist(
            id=row["id"],
            name=row["name"],
            description=row["description"],
            sort_order=row["sort_order"],
            remote_playlist_id=row["remote_playlist_id"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def assign_source_playlist_to_destination(
        self, source_playlist_id: int, destination_id: int
    ) -> int:
        """Copy all non-own tracks from a source playlist into a destination."""
        cur = execute(
            self.conn,
            """
            INSERT OR IGNORE INTO track_assignments(track_id, destination_playlist_id)
            SELECT pi.track_id, ?
            FROM playlist_items pi
            JOIN tracks t ON t.id = pi.track_id
            WHERE pi.source_playlist_id = ?
              AND COALESCE(t.is_own_upload, 0) = 0
            """,
            (destination_id, source_playlist_id),
        )
        return int(cur.rowcount or 0)

    def rename_destination(self, dest_id: int, name: str) -> None:
        self.update_destination(dest_id, name=name)

    def update_destination(
        self,
        dest_id: int,
        *,
        name: str | None = None,
        description: str | None = None,
        set_description: bool = False,
    ) -> None:
        fields: list[str] = []
        params: list[Any] = []
        if name is not None:
            fields.append("name = ?")
            params.append(name.strip())
        if set_description:
            fields.append("description = ?")
            params.append(description)
        if not fields:
            return
        fields.append("updated_at = datetime('now')")
        params.append(dest_id)
        execute(
            self.conn,
            f"UPDATE destination_playlists SET {', '.join(fields)} WHERE id = ?",
            params,
        )

    def merge_destinations(self, source_ids: Sequence[int], target_id: int) -> int:
        sources = sorted({int(item) for item in source_ids if int(item) != int(target_id)})
        if not sources:
            raise ValueError("Pick at least one other playlist to merge.")
        target = fetchone(
            self.conn,
            "SELECT id FROM destination_playlists WHERE id = ?",
            (int(target_id),),
        )
        if target is None:
            raise ValueError("Keep playlist was not found.")
        missing = [
            source_id
            for source_id in sources
            if fetchone(
                self.conn,
                "SELECT id FROM destination_playlists WHERE id = ?",
                (source_id,),
            )
            is None
        ]
        if missing:
            raise ValueError("One or more playlists to merge were not found.")

        moved = 0
        with transaction(self.conn):
            for source_id in sources:
                cur = execute(
                    self.conn,
                    """
                    INSERT OR IGNORE INTO track_assignments(
                        track_id, destination_playlist_id, position, assigned_at
                    )
                    SELECT track_id, ?, position, assigned_at
                    FROM track_assignments
                    WHERE destination_playlist_id = ?
                    """,
                    (int(target_id), source_id),
                )
                moved += int(cur.rowcount or 0)
                execute(
                    self.conn,
                    "DELETE FROM track_assignments WHERE destination_playlist_id = ?",
                    (source_id,),
                )
                execute(
                    self.conn,
                    "DELETE FROM destination_playlists WHERE id = ?",
                    (source_id,),
                )
        return moved

    def delete_destination(self, dest_id: int) -> None:
        with transaction(self.conn):
            execute(
                self.conn,
                "DELETE FROM track_assignments WHERE destination_playlist_id = ?",
                (dest_id,),
            )
            execute(self.conn, "DELETE FROM destination_playlists WHERE id = ?", (dest_id,))

    def list_destinations(self) -> list[DestinationPlaylist]:
        rows = fetchall(
            self.conn,
            "SELECT * FROM destination_playlists ORDER BY sort_order ASC, name COLLATE NOCASE",
        )
        return [
            DestinationPlaylist(
                id=r["id"],
                name=r["name"],
                description=r["description"],
                sort_order=r["sort_order"],
                remote_playlist_id=r["remote_playlist_id"],
                created_at=r["created_at"],
                updated_at=r["updated_at"],
            )
            for r in rows
        ]

    def set_destination_remote_id(self, dest_id: int, remote_playlist_id: str) -> None:
        execute(
            self.conn,
            """
            UPDATE destination_playlists
            SET remote_playlist_id = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (remote_playlist_id, dest_id),
        )

    def get_assignment_destination_ids(self, track_id: int) -> list[int]:
        rows = fetchall(
            self.conn,
            "SELECT destination_playlist_id FROM track_assignments WHERE track_id = ?",
            (track_id,),
        )
        return [int(r["destination_playlist_id"]) for r in rows]

    def assign_track(
        self, track_id: int, destination_id: int, *, record_history: bool = True
    ) -> None:
        previous = self.get_assignment_destination_ids(track_id)
        with transaction(self.conn):
            execute(
                self.conn,
                """
                INSERT OR IGNORE INTO track_assignments(track_id, destination_playlist_id)
                VALUES (?, ?)
                """,
                (track_id, destination_id),
            )
            if record_history:
                execute(
                    self.conn,
                    """
                    INSERT INTO assignment_history(action, track_id, destination_playlist_id, previous_destination_ids)
                    VALUES ('assign', ?, ?, ?)
                    """,
                    (track_id, destination_id, json.dumps(previous)),
                )

    def unassign_track(
        self, track_id: int, destination_id: int | None = None, *, record_history: bool = True
    ) -> None:
        previous = self.get_assignment_destination_ids(track_id)
        with transaction(self.conn):
            if destination_id is None:
                execute(
                    self.conn, "DELETE FROM track_assignments WHERE track_id = ?", (track_id,)
                )
            else:
                execute(
                    self.conn,
                    """
                    DELETE FROM track_assignments
                    WHERE track_id = ? AND destination_playlist_id = ?
                    """,
                    (track_id, destination_id),
                )
            if record_history:
                execute(
                    self.conn,
                    """
                    INSERT INTO assignment_history(action, track_id, destination_playlist_id, previous_destination_ids)
                    VALUES ('unassign', ?, ?, ?)
                    """,
                    (track_id, destination_id, json.dumps(previous)),
                )

    def set_track_assignments(self, track_id: int, destination_ids: Sequence[int]) -> None:
        previous = self.get_assignment_destination_ids(track_id)
        with transaction(self.conn):
            execute(self.conn, "DELETE FROM track_assignments WHERE track_id = ?", (track_id,))
            for dest_id in destination_ids:
                execute(
                    self.conn,
                    """
                    INSERT INTO track_assignments(track_id, destination_playlist_id)
                    VALUES (?, ?)
                    """,
                    (track_id, dest_id),
                )
            execute(
                self.conn,
                """
                INSERT INTO assignment_history(action, track_id, destination_playlist_id, previous_destination_ids)
                VALUES ('set', ?, ?, ?)
                """,
                (
                    track_id,
                    destination_ids[0] if destination_ids else None,
                    json.dumps(previous),
                ),
            )

    def bulk_assign(self, track_ids: Iterable[int], destination_id: int) -> int:
        count = 0
        with transaction(self.conn):
            for track_id in track_ids:
                previous = self.get_assignment_destination_ids(track_id)
                execute(
                    self.conn,
                    """
                    INSERT OR IGNORE INTO track_assignments(track_id, destination_playlist_id)
                    VALUES (?, ?)
                    """,
                    (track_id, destination_id),
                )
                execute(
                    self.conn,
                    """
                    INSERT INTO assignment_history(action, track_id, destination_playlist_id, previous_destination_ids)
                    VALUES ('assign', ?, ?, ?)
                    """,
                    (track_id, destination_id, json.dumps(previous)),
                )
                count += 1
        return count

    def undo_last_assignment(self) -> bool:
        row = fetchone(
            self.conn,
            """
            SELECT * FROM assignment_history
            WHERE undone = 0
            ORDER BY id DESC LIMIT 1
            """,
        )
        if not row:
            return False
        previous = json.loads(row["previous_destination_ids"] or "[]")
        track_id = int(row["track_id"])
        with transaction(self.conn):
            execute(self.conn, "DELETE FROM track_assignments WHERE track_id = ?", (track_id,))
            for dest_id in previous:
                execute(
                    self.conn,
                    """
                    INSERT INTO track_assignments(track_id, destination_playlist_id)
                    VALUES (?, ?)
                    """,
                    (track_id, int(dest_id)),
                )
            execute(
                self.conn,
                "UPDATE assignment_history SET undone = 1 WHERE id = ?",
                (row["id"],),
            )
        return True

    # ---- catalogue queries ----
    def catalogue_query(
        self,
        *,
        search: str | None = None,
        artist: str | None = None,
        album: str | None = None,
        source_playlist_id: int | None = None,
        destination_playlist_id: int | None = None,
        assignment_filter: str | None = None,
        availability: str | None = None,
        multi_source_only: bool = False,
        limit: int = 50,
        offset: int = 0,
        sort_by: str = "title",
        sort_dir: str = "ASC",
        exclude_own_uploads: bool = True,
    ) -> tuple[list[sqlite3.Row], int]:
        allowed_sort = {
            "title": "t.title",
            "artists": "t.artists",
            "album": "t.album",
            "duration_seconds": "t.duration_seconds",
            "availability": "t.availability",
            "last_seen_at": "t.last_seen_at",
        }
        sort_col = allowed_sort.get(sort_by, "t.title")
        direction = "DESC" if sort_dir.upper() == "DESC" else "ASC"

        where = ["1=1"]
        params: list[Any] = []
        if exclude_own_uploads:
            where.append("COALESCE(t.is_own_upload, 0) = 0")

        if search:
            where.append("(t.title LIKE ? OR t.artists LIKE ? OR t.album LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like, like])
        if artist:
            where.append("t.artists LIKE ?")
            params.append(f"%{artist}%")
        if album:
            where.append("t.album LIKE ?")
            params.append(f"%{album}%")
        if availability:
            where.append("t.availability = ?")
            params.append(availability)
        if source_playlist_id is not None:
            where.append(
                "EXISTS (SELECT 1 FROM playlist_items pi "
                "WHERE pi.track_id = t.id AND pi.source_playlist_id = ?)"
            )
            params.append(source_playlist_id)
        if destination_playlist_id is not None:
            where.append(
                "EXISTS (SELECT 1 FROM track_assignments ta "
                "WHERE ta.track_id = t.id AND ta.destination_playlist_id = ?)"
            )
            params.append(destination_playlist_id)
        if assignment_filter == "assigned":
            where.append(
                "EXISTS (SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id)"
            )
        elif assignment_filter == "unassigned":
            where.append(
                "NOT EXISTS (SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id)"
            )
        if multi_source_only:
            where.append(
                "(SELECT COUNT(DISTINCT pi.source_playlist_id) FROM playlist_items pi "
                "WHERE pi.track_id = t.id) > 1"
            )

        where_sql = " AND ".join(where)
        count_row = fetchone(
            self.conn,
            f"SELECT COUNT(*) AS c FROM tracks t WHERE {where_sql}",
            params,
        )
        total = int(count_row["c"]) if count_row else 0

        rows = fetchall(
            self.conn,
            f"""
            SELECT t.*,
                   (SELECT COUNT(DISTINCT pi.source_playlist_id) FROM playlist_items pi
                    WHERE pi.track_id = t.id) AS source_count,
                   (SELECT GROUP_CONCAT(sp.title, ' | ')
                    FROM playlist_items pi
                    JOIN source_playlists sp ON sp.id = pi.source_playlist_id
                    WHERE pi.track_id = t.id) AS source_memberships,
                   (SELECT GROUP_CONCAT(dp.name, ' | ')
                    FROM track_assignments ta
                    JOIN destination_playlists dp ON dp.id = ta.destination_playlist_id
                    WHERE ta.track_id = t.id) AS destination_memberships,
                   (SELECT COUNT(*) FROM track_assignments ta WHERE ta.track_id = t.id) AS assignment_count
            FROM tracks t
            WHERE {where_sql}
            ORDER BY {sort_col} {direction}
            LIMIT ? OFFSET ?
            """,
            [*params, limit, offset],
        )
        return rows, total

    def get_memberships_for_tracks(self, track_ids: Sequence[int]) -> dict[int, list[str]]:
        if not track_ids:
            return {}
        placeholders = ",".join("?" for _ in track_ids)
        rows = fetchall(
            self.conn,
            f"""
            SELECT pi.track_id, sp.title
            FROM playlist_items pi
            JOIN source_playlists sp ON sp.id = pi.source_playlist_id
            WHERE pi.track_id IN ({placeholders})
            ORDER BY sp.title
            """,
            list(track_ids),
        )
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(int(r["track_id"]), []).append(r["title"])
        return out

    def destination_tracks(self, destination_id: int) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT t.*, ta.position, ta.assigned_at
            FROM track_assignments ta
            JOIN tracks t ON t.id = ta.track_id
            WHERE ta.destination_playlist_id = ?
              AND COALESCE(t.is_own_upload, 0) = 0
            ORDER BY COALESCE(ta.position, 999999), t.title COLLATE NOCASE
            """,
            (destination_id,),
        )

    def unassigned_tracks(self) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT t.* FROM tracks t
            WHERE COALESCE(t.is_own_upload, 0) = 0
              AND NOT EXISTS (
                SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id
            )
            ORDER BY t.title COLLATE NOCASE
            """,
        )

    def multi_assigned_tracks(self) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT t.*, COUNT(ta.id) AS dest_count,
                   GROUP_CONCAT(dp.name, ' | ') AS destinations
            FROM tracks t
            JOIN track_assignments ta ON ta.track_id = t.id
            JOIN destination_playlists dp ON dp.id = ta.destination_playlist_id
            WHERE COALESCE(t.is_own_upload, 0) = 0
            GROUP BY t.id
            HAVING COUNT(ta.id) > 1
            ORDER BY t.title COLLATE NOCASE
            """,
        )

    def unresolved_tracks(self) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT * FROM tracks
            WHERE COALESCE(is_own_upload, 0) = 0
              AND (needs_review = 1 OR video_id IS NULL OR availability IN ('unknown', 'missing_id'))
            ORDER BY title COLLATE NOCASE
            """,
        )

    def insert_ambiguous(
        self,
        *,
        title: str,
        artists: str,
        album: str | None,
        source_playlist_id: int | None,
        position: int | None,
        reason: str,
        raw_json: str | None,
    ) -> None:
        execute(
            self.conn,
            """
            INSERT INTO ambiguous_tracks(
                title, artists, album, source_playlist_id, position, reason, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (title, artists, album, source_playlist_id, position, reason, raw_json),
        )

    # ---- operation logs ----
    def log_operation(
        self,
        *,
        operation_type: str,
        status: str,
        destination_playlist_id: int | None = None,
        track_id: int | None = None,
        video_id: str | None = None,
        remote_playlist_id: str | None = None,
        message: str | None = None,
        idempotency_key: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> int:
        cur = execute(
            self.conn,
            """
            INSERT OR IGNORE INTO operation_logs(
                operation_type, status, destination_playlist_id, track_id, video_id,
                remote_playlist_id, message, idempotency_key, details_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                operation_type,
                status,
                destination_playlist_id,
                track_id,
                video_id,
                remote_playlist_id,
                message,
                idempotency_key,
                json.dumps(details or {}),
            ),
        )
        return int(cur.lastrowid or 0)

    def operation_succeeded(self, idempotency_key: str) -> bool:
        row = fetchone(
            self.conn,
            """
            SELECT id FROM operation_logs
            WHERE idempotency_key = ? AND status = 'success'
            """,
            (idempotency_key,),
        )
        return row is not None

    def operation_failed(self, idempotency_key: str) -> bool:
        row = fetchone(
            self.conn,
            """
            SELECT id FROM operation_logs
            WHERE idempotency_key = ? AND status = 'failed'
            """,
            (idempotency_key,),
        )
        return row is not None

    def list_failed_operations(self) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            """
            SELECT * FROM operation_logs
            WHERE status = 'failed'
            ORDER BY id DESC
            """,
        )

    def list_operations(self, limit: int = 200) -> list[sqlite3.Row]:
        return fetchall(
            self.conn,
            "SELECT * FROM operation_logs ORDER BY id DESC LIMIT ?",
            (limit,),
        )

    def update_operation_status(
        self, op_id: int, status: str, message: str | None = None
    ) -> None:
        execute(
            self.conn,
            "UPDATE operation_logs SET status = ?, message = COALESCE(?, message) WHERE id = ?",
            (status, message, op_id),
        )

    # ---- dashboard ----
    def dashboard_stats(self) -> DashboardStats:
        source_playlists = fetchone(self.conn, "SELECT COUNT(*) AS c FROM source_playlists")
        playlist_entries = fetchone(self.conn, "SELECT COUNT(*) AS c FROM playlist_items")
        unique_tracks = fetchone(
            self.conn, "SELECT COUNT(*) AS c FROM tracks WHERE COALESCE(is_own_upload, 0) = 0"
        )
        multi = fetchone(
            self.conn,
            """
            SELECT COALESCE(SUM(cnt - 1), 0) AS c FROM (
                SELECT COUNT(*) AS cnt FROM playlist_items GROUP BY track_id HAVING COUNT(*) > 1
            )
            """,
        )
        uncertain = fetchone(
            self.conn,
            """
            SELECT COUNT(*) AS c FROM tracks
            WHERE COALESCE(is_own_upload, 0) = 0
              AND (availability NOT IN ('available') OR needs_review = 1 OR video_id IS NULL)
            """,
        )
        assigned = fetchone(
            self.conn,
            """
            SELECT COUNT(DISTINCT track_id) AS c FROM track_assignments
            """,
        )
        unassigned = fetchone(
            self.conn,
            """
            SELECT COUNT(*) AS c FROM tracks t
            WHERE COALESCE(t.is_own_upload, 0) = 0
              AND NOT EXISTS (SELECT 1 FROM track_assignments ta WHERE ta.track_id = t.id)
            """,
        )
        return DashboardStats(
            source_playlists=int(source_playlists["c"] if source_playlists else 0),
            playlist_entries=int(playlist_entries["c"] if playlist_entries else 0),
            unique_tracks=int(unique_tracks["c"] if unique_tracks else 0),
            duplicate_occurrences=int(multi["c"] if multi else 0),
            unavailable_or_uncertain=int(uncertain["c"] if uncertain else 0),
            assigned_tracks=int(assigned["c"] if assigned else 0),
            unassigned_tracks=int(unassigned["c"] if unassigned else 0),
            last_successful_import_at=self.last_successful_import_at(),
        )

    # ---- background jobs ----
    def create_job(self, job_type: str, payload: dict[str, Any] | None = None) -> int:
        cur = execute(
            self.conn,
            """
            INSERT INTO background_jobs(job_type, status, payload_json)
            VALUES (?, 'queued', ?)
            """,
            (job_type, json.dumps(payload or {})),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def get_job(self, job_id: int) -> sqlite3.Row | None:
        return fetchone(self.conn, "SELECT * FROM background_jobs WHERE id = ?", (job_id,))

    def latest_job(self, job_type: str) -> sqlite3.Row | None:
        return fetchone(
            self.conn,
            """
            SELECT * FROM background_jobs
            WHERE job_type = ?
            ORDER BY id DESC LIMIT 1
            """,
            (job_type,),
        )

    def latest_job_in(self, job_types: Sequence[str]) -> sqlite3.Row | None:
        if not job_types:
            return None
        placeholders = ",".join("?" for _ in job_types)
        return fetchone(
            self.conn,
            f"""
            SELECT * FROM background_jobs
            WHERE job_type IN ({placeholders})
            ORDER BY id DESC LIMIT 1
            """,
            list(job_types),
        )

    def active_job_in(self, job_types: Sequence[str]) -> sqlite3.Row | None:
        if not job_types:
            return None
        type_ph = ",".join("?" for _ in job_types)
        status_ph = ",".join("?" for _ in ACTIVE_JOB_STATUSES)
        return fetchone(
            self.conn,
            f"""
            SELECT * FROM background_jobs
            WHERE job_type IN ({type_ph})
              AND status IN ({status_ph})
            ORDER BY id DESC LIMIT 1
            """,
            list(job_types) + sorted(ACTIVE_JOB_STATUSES),
        )

    def set_job_status(self, job_id: int, status: str, message: str | None = None) -> None:
        terminal_ph = ",".join("?" for _ in TERMINAL_JOB_STATUSES)
        execute(
            self.conn,
            f"""
            UPDATE background_jobs SET
                status = ?,
                message = COALESCE(?, message),
                finished_at = CASE WHEN ? IN ({terminal_ph})
                    THEN datetime('now') ELSE finished_at END,
                updated_at = datetime('now')
            WHERE id = ?
            """,
            (status, message, status, *sorted(TERMINAL_JOB_STATUSES), job_id),
        )
        self.conn.commit()

    def set_job_command(self, job_id: int, command: str) -> None:
        execute(
            self.conn,
            """
            UPDATE background_jobs
            SET command = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (command, job_id),
        )
        self.conn.commit()

    def set_job_error(self, job_id: int, error: str) -> None:
        execute(
            self.conn,
            """
            UPDATE background_jobs SET
                status = 'failed', error = ?, message = ?,
                finished_at = datetime('now'), updated_at = datetime('now')
            WHERE id = ?
            """,
            (error, error, job_id),
        )
        self.conn.commit()

    def append_job_log(self, job_id: int, line: str) -> None:
        row = self.get_job(job_id)
        previous = str(row["logs"] or "") if row else ""
        lines = [part for part in previous.splitlines() if part] + [line]
        logs = "\n".join(lines[-400:])
        execute(
            self.conn,
            """
            UPDATE background_jobs
            SET logs = ?, message = ?, updated_at = datetime('now')
            WHERE id = ?
            """,
            (logs, line, job_id),
        )
        self.conn.commit()

    def export_plan_rows(self) -> list[dict[str, Any]]:
        rows = fetchall(
            self.conn,
            """
            SELECT t.id AS track_id, t.video_id, t.title, t.artists, t.album,
                   t.duration_seconds, t.duration_text, t.canonical_url, t.availability,
                   t.needs_review,
                   (SELECT GROUP_CONCAT(sp.title, ' | ')
                    FROM playlist_items pi
                    JOIN source_playlists sp ON sp.id = pi.source_playlist_id
                    WHERE pi.track_id = t.id) AS source_playlists,
                   (SELECT GROUP_CONCAT(dp.name, ' | ')
                    FROM track_assignments ta
                    JOIN destination_playlists dp ON dp.id = ta.destination_playlist_id
                    WHERE ta.track_id = t.id) AS destination_playlists
            FROM tracks t
            WHERE COALESCE(t.is_own_upload, 0) = 0
            ORDER BY t.title COLLATE NOCASE
            """,
        )
        return [dict(r) for r in rows]


def _playlist_id_candidates(playlist_id: str) -> list[str]:
    pid = playlist_id.strip()
    out = [pid]
    bare = pid.removeprefix("VL")
    if bare not in out:
        out.append(bare)
    prefixed = f"VL{bare}"
    if prefixed not in out:
        out.append(prefixed)
    return out
