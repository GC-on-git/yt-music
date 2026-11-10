"""CSV / JSON export of the organization plan."""

from __future__ import annotations

import csv
import json
from io import StringIO
from pathlib import Path
from typing import Any

from src.db.repository import Repository


class ExportService:
    def __init__(self, repo: Repository) -> None:
        self.repo = repo

    def plan_rows(self) -> list[dict[str, Any]]:
        return self.repo.export_plan_rows()

    def to_json(self) -> str:
        payload = {
            "destinations": [
                {
                    "id": d.id,
                    "name": d.name,
                    "description": d.description,
                    "remote_playlist_id": d.remote_playlist_id,
                    "tracks": [
                        {
                            "track_id": r["id"],
                            "video_id": r["video_id"],
                            "title": r["title"],
                            "artists": r["artists"],
                            "album": r["album"],
                            "canonical_url": r["canonical_url"],
                        }
                        for r in self.repo.destination_tracks(d.id)
                    ],
                }
                for d in self.repo.list_destinations()
            ],
            "unassigned": [
                {
                    "track_id": r["id"],
                    "video_id": r["video_id"],
                    "title": r["title"],
                    "artists": r["artists"],
                    "source_hint": None,
                }
                for r in self.repo.unassigned_tracks()
            ],
            "multi_assigned": [dict(r) for r in self.repo.multi_assigned_tracks()],
            "unresolved": [dict(r) for r in self.repo.unresolved_tracks()],
            "catalogue": self.plan_rows(),
        }
        return json.dumps(payload, indent=2, ensure_ascii=False, default=str)

    def to_csv(self) -> str:
        rows = self.plan_rows()
        buffer = StringIO()
        fieldnames = [
            "track_id",
            "video_id",
            "title",
            "artists",
            "album",
            "duration_seconds",
            "duration_text",
            "canonical_url",
            "availability",
            "needs_review",
            "source_playlists",
            "destination_playlists",
        ]
        writer = csv.DictWriter(buffer, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow(row)
        return buffer.getvalue()

    def write_json(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_json(), encoding="utf-8")
        return path

    def write_csv(self, path: Path) -> Path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.to_csv(), encoding="utf-8")
        return path
