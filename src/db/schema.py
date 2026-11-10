"""Versioned SQLite schema and migrations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable

from src.db.dedupe_tracks import dedupe_tracks_by_title_artist, ensure_title_artist_unique_index

SCHEMA_VERSION = 6


def _table_columns(conn: sqlite3.Connection, table: str) -> set[str]:
    rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
    return {str(row[1]) for row in rows}


def _add_column_if_missing(conn: sqlite3.Connection, table: str, name: str, decl: str) -> None:
    if name in _table_columns(conn, table):
        return
    conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")


def _migrate_track_channel_columns(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "tracks", "channel_id", "TEXT")
    _add_column_if_missing(conn, "tracks", "channel_title", "TEXT")
    _add_column_if_missing(conn, "tracks", "is_own_upload", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_own_upload ON tracks(is_own_upload)")


def _migrate_smart_assigned(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(conn, "tracks", "smart_assigned", "INTEGER NOT NULL DEFAULT 0")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_tracks_smart_assigned ON tracks(smart_assigned)")


def _migrate_source_smart_assign(conn: sqlite3.Connection) -> None:
    _add_column_if_missing(
        conn, "source_playlists", "include_in_smart_assign", "INTEGER NOT NULL DEFAULT 0"
    )
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_source_playlists_smart_assign "
        "ON source_playlists(include_in_smart_assign)"
    )


MIGRATIONS: dict[int, list[str]] = {
    1: [
        """
        CREATE TABLE IF NOT EXISTS schema_migrations (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            video_id TEXT,
            title TEXT NOT NULL,
            artists TEXT NOT NULL DEFAULT '',
            album TEXT,
            duration_seconds INTEGER,
            duration_text TEXT,
            canonical_url TEXT,
            thumbnail_url TEXT,
            availability TEXT NOT NULL DEFAULT 'unknown',
            needs_review INTEGER NOT NULL DEFAULT 0,
            review_reason TEXT,
            channel_id TEXT,
            channel_title TEXT,
            is_own_upload INTEGER NOT NULL DEFAULT 0,
            smart_assigned INTEGER NOT NULL DEFAULT 0,
            first_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(video_id)
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tracks_title ON tracks(title)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tracks_artists ON tracks(artists)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tracks_availability ON tracks(availability)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tracks_own_upload ON tracks(is_own_upload)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_tracks_smart_assigned ON tracks(smart_assigned)
        """,
        """
        CREATE TABLE IF NOT EXISTS source_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            playlist_id TEXT NOT NULL UNIQUE,
            title TEXT NOT NULL,
            url TEXT,
            privacy TEXT,
            description TEXT,
            owned INTEGER,
            track_count_remote INTEGER,
            last_import_at TEXT,
            import_status TEXT NOT NULL DEFAULT 'pending',
            last_error TEXT,
            include_in_smart_assign INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_source_playlists_smart_assign
            ON source_playlists(include_in_smart_assign)
        """,
        """
        CREATE TABLE IF NOT EXISTS playlist_items (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            source_playlist_id INTEGER NOT NULL,
            position INTEGER NOT NULL,
            set_video_id TEXT,
            import_run_id INTEGER,
            availability TEXT,
            raw_title TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(source_playlist_id, position, set_video_id, track_id),
            FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE,
            FOREIGN KEY(source_playlist_id) REFERENCES source_playlists(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_playlist_items_track ON playlist_items(track_id)
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_playlist_items_playlist ON playlist_items(source_playlist_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS destination_playlists (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            remote_playlist_id TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS track_assignments (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            track_id INTEGER NOT NULL,
            destination_playlist_id INTEGER NOT NULL,
            position INTEGER,
            assigned_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(track_id, destination_playlist_id),
            FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE,
            FOREIGN KEY(destination_playlist_id) REFERENCES destination_playlists(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE INDEX IF NOT EXISTS idx_assignments_dest ON track_assignments(destination_playlist_id)
        """,
        """
        CREATE TABLE IF NOT EXISTS import_runs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            started_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT,
            mode TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending',
            playlists_total INTEGER NOT NULL DEFAULT 0,
            playlists_succeeded INTEGER NOT NULL DEFAULT 0,
            playlists_failed INTEGER NOT NULL DEFAULT 0,
            tracks_seen INTEGER NOT NULL DEFAULT 0,
            unique_tracks_upserted INTEGER NOT NULL DEFAULT 0,
            error_summary TEXT
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS operation_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            operation_type TEXT NOT NULL,
            status TEXT NOT NULL,
            destination_playlist_id INTEGER,
            track_id INTEGER,
            video_id TEXT,
            remote_playlist_id TEXT,
            message TEXT,
            idempotency_key TEXT UNIQUE,
            details_json TEXT,
            FOREIGN KEY(destination_playlist_id) REFERENCES destination_playlists(id) ON DELETE SET NULL,
            FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE SET NULL
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS assignment_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            action TEXT NOT NULL,
            track_id INTEGER NOT NULL,
            destination_playlist_id INTEGER,
            previous_destination_ids TEXT NOT NULL DEFAULT '[]',
            undone INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(track_id) REFERENCES tracks(id) ON DELETE CASCADE
        )
        """,
        """
        CREATE TABLE IF NOT EXISTS ambiguous_tracks (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            artists TEXT NOT NULL DEFAULT '',
            album TEXT,
            source_playlist_id INTEGER,
            position INTEGER,
            reason TEXT NOT NULL,
            raw_json TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            resolved INTEGER NOT NULL DEFAULT 0,
            FOREIGN KEY(source_playlist_id) REFERENCES source_playlists(id) ON DELETE SET NULL
        )
        """,
    ],
    2: [],
    3: [],
    4: [],
    5: [
        """
        CREATE TABLE IF NOT EXISTS background_jobs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            job_type TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'queued',
            command TEXT NOT NULL DEFAULT '',
            message TEXT,
            logs TEXT NOT NULL DEFAULT '',
            payload_json TEXT NOT NULL DEFAULT '{}',
            error TEXT,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            finished_at TEXT
        )
        """,
        "CREATE INDEX IF NOT EXISTS idx_background_jobs_type ON background_jobs(job_type, status)",
    ],
    6: [],
}


def _migrate_unique_tracks(conn: sqlite3.Connection) -> None:
    dedupe_tracks_by_title_artist(conn)
    ensure_title_artist_unique_index(conn)


POST_MIGRATIONS: dict[int, Callable[[sqlite3.Connection], None]] = {
    2: _migrate_track_channel_columns,
    3: _migrate_smart_assigned,
    4: _migrate_source_smart_assign,
    6: _migrate_unique_tracks,
}


def get_schema_version(conn: sqlite3.Connection) -> int:
    row = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='schema_migrations'"
    ).fetchone()
    if not row:
        return 0
    version_row = conn.execute("SELECT COALESCE(MAX(version), 0) AS v FROM schema_migrations").fetchone()
    return int(version_row["v"] if version_row else 0)


def migrate(conn: sqlite3.Connection) -> int:
    current = get_schema_version(conn)
    target = SCHEMA_VERSION
    for version in range(current + 1, target + 1):
        statements = MIGRATIONS.get(version, [])
        for sql in statements:
            conn.execute(sql)
        post = POST_MIGRATIONS.get(version)
        if post is not None:
            post(conn)
        conn.execute(
            "INSERT OR IGNORE INTO schema_migrations(version) VALUES (?)",
            (version,),
        )
    conn.commit()
    return get_schema_version(conn)


def init_db(conn: sqlite3.Connection) -> int:
    return migrate(conn)
