"""Backup and restore the local SQLite database."""

from __future__ import annotations

import shutil
from datetime import datetime, timezone
from pathlib import Path

from src.config import get_settings


class BackupService:
    def __init__(self, db_path: Path | None = None, backup_dir: Path | None = None) -> None:
        settings = get_settings()
        self.db_path = db_path or settings.database_path
        self.backup_dir = backup_dir or settings.backup_dir

    def backup(self) -> Path:
        if not self.db_path.exists():
            raise FileNotFoundError(f"Database not found at {self.db_path}")
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        dest = self.backup_dir / f"organizer-{stamp}.db"
        shutil.copy2(self.db_path, dest)
        return dest

    def restore(self, backup_path: Path) -> Path:
        if not backup_path.exists():
            raise FileNotFoundError(f"Backup not found: {backup_path}")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        if self.db_path.exists():
            safety = self.db_path.with_suffix(".db.pre-restore")
            shutil.copy2(self.db_path, safety)
        shutil.copy2(backup_path, self.db_path)
        return self.db_path

    def list_backups(self) -> list[Path]:
        if not self.backup_dir.exists():
            return []
        return sorted(self.backup_dir.glob("organizer-*.db"), reverse=True)
