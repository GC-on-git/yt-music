"""Shared Streamlit/app wiring: DB, adapter, services."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from src.config import Settings, get_settings
from src.db.connection import connect
from src.db.repository import Repository
from src.db.schema import init_db
from src.integrations.base import YouTubeMusicClient
from src.integrations.llm import LlmClient
from src.integrations.ytmusic_adapter import build_default_adapter
from src.logging_config import configure_logging
from src.services.assignment_service import AssignmentService
from src.services.backup_service import BackupService
from src.services.export_service import ExportService
from src.services.import_service import ImportService
from src.services.remote_apply_service import RemoteApplyService
from src.services.smart_assign_service import SmartAssignService


@dataclass
class AppContext:
    settings: Settings
    conn: sqlite3.Connection
    repo: Repository
    client: YouTubeMusicClient
    imports: ImportService
    assignments: AssignmentService
    exports: ExportService
    remote: RemoteApplyService
    backups: BackupService
    smart: SmartAssignService


_CONTEXT: AppContext | None = None


def get_context(force_reload: bool = False) -> AppContext:
    global _CONTEXT
    if _CONTEXT is not None and not force_reload:
        return _CONTEXT

    settings = get_settings()
    configure_logging(settings.log_level)
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    conn = connect(settings.database_path)
    init_db(conn)
    repo = Repository(conn)
    client = build_default_adapter(settings)
    assignments = AssignmentService(repo)
    _CONTEXT = AppContext(
        settings=settings,
        conn=conn,
        repo=repo,
        client=client,
        imports=ImportService(repo, client),
        assignments=assignments,
        exports=ExportService(repo),
        remote=RemoteApplyService(repo, client),
        backups=BackupService(settings.database_path, settings.backup_dir),
        smart=SmartAssignService(repo, assignments, LlmClient(settings)),
    )
    return _CONTEXT


def reset_context() -> None:
    global _CONTEXT
    if _CONTEXT is not None:
        try:
            _CONTEXT.conn.close()
        except Exception:  # noqa: BLE001
            pass
    _CONTEXT = None
    get_settings.cache_clear() if hasattr(get_settings, "cache_clear") else None
