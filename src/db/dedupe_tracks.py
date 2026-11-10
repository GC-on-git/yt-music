"""Merge duplicate track rows that share the same title + artist."""

from __future__ import annotations

import sqlite3

from src.db.track_identity import track_identity_key


def dedupe_tracks_by_title_artist(conn: sqlite3.Connection) -> int:
    """Collapse duplicate tracks onto one survivor. Returns rows removed."""
    rows = list(
        conn.execute(
            """
            SELECT id, video_id, title, artists, smart_assigned, needs_review
            FROM tracks
            ORDER BY id ASC
            """
        )
    )
    groups: dict[tuple[str, str], list[sqlite3.Row]] = {}
    for row in rows:
        key = track_identity_key(row["title"], row["artists"])
        if not key[0]:
            continue
        groups.setdefault(key, []).append(row)

    removed = 0
    for members in groups.values():
        if len(members) < 2:
            continue
        survivor = _pick_survivor(members)
        for duplicate in members:
            if int(duplicate["id"]) == int(survivor["id"]):
                continue
            _repoint_track(conn, int(duplicate["id"]), int(survivor["id"]))
            conn.execute("DELETE FROM tracks WHERE id = ?", (int(duplicate["id"]),))
            removed += 1
        _refresh_survivor_flags(conn, int(survivor["id"]), members)
    return removed


def ensure_title_artist_unique_index(conn: sqlite3.Connection) -> None:
    conn.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tracks_title_artists_unique
        ON tracks (lower(trim(title)), lower(trim(artists)))
        WHERE length(trim(title)) > 0
        """
    )


def _pick_survivor(members: list[sqlite3.Row]) -> sqlite3.Row:
    with_video = [row for row in members if row["video_id"]]
    pool = with_video or members
    return min(pool, key=lambda row: int(row["id"]))


def _repoint_track(conn: sqlite3.Connection, old_id: int, new_id: int) -> None:
    conn.execute(
        """
        INSERT OR IGNORE INTO playlist_items (
            track_id, source_playlist_id, position, set_video_id,
            import_run_id, availability, raw_title, created_at
        )
        SELECT ?, source_playlist_id, position, set_video_id,
               import_run_id, availability, raw_title, created_at
        FROM playlist_items
        WHERE track_id = ?
        """,
        (new_id, old_id),
    )
    conn.execute("DELETE FROM playlist_items WHERE track_id = ?", (old_id,))

    conn.execute(
        """
        INSERT OR IGNORE INTO track_assignments (
            track_id, destination_playlist_id, position, assigned_at
        )
        SELECT ?, destination_playlist_id, position, assigned_at
        FROM track_assignments
        WHERE track_id = ?
        """,
        (new_id, old_id),
    )
    conn.execute("DELETE FROM track_assignments WHERE track_id = ?", (old_id,))

    conn.execute(
        "UPDATE assignment_history SET track_id = ? WHERE track_id = ?",
        (new_id, old_id),
    )
    conn.execute(
        "UPDATE operation_logs SET track_id = ? WHERE track_id = ?",
        (new_id, old_id),
    )


def _refresh_survivor_flags(
    conn: sqlite3.Connection, survivor_id: int, members: list[sqlite3.Row]
) -> None:
    smart = any(int(row["smart_assigned"] or 0) for row in members)
    review = any(int(row["needs_review"] or 0) for row in members)
    conn.execute(
        """
        UPDATE tracks
        SET smart_assigned = CASE WHEN ? THEN 1 ELSE smart_assigned END,
            needs_review = CASE WHEN ? THEN 1 ELSE needs_review END
        WHERE id = ?
        """,
        (1 if smart else 0, 1 if review else 0, survivor_id),
    )
