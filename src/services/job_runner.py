"""Background jobs for import, smart assign, and publish."""

from __future__ import annotations

import json
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Any

from src.config import get_settings
from src.db.connection import connect, with_retry
from src.db.repository import Repository
from src.db.schema import init_db
from src.integrations.llm import LlmClient
from src.integrations.ytmusic_adapter import build_default_adapter
from src.logging_config import get_logger, safe_error_message
from src.services.assignment_service import AssignmentService
from src.models.state_machines import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    apply_job_command,
    can_apply_job_command,
)
from src.services.import_service import ImportService
from src.services.remote_apply_service import RemoteApplyService
from src.services.smart_assign_service import SmartAssignService

logger = get_logger(__name__)

IMPORT_TYPES = ("import_library", "import_playlist", "import_retry")
SMART_TYPE = "smart_assign"
PUBLISH_TYPE = "publish"
ACTIVE = tuple(ACTIVE_JOB_STATUSES)

_EXECUTOR = ThreadPoolExecutor(max_workers=3, thread_name_prefix="ytm-job")
_START_LOCK = threading.Lock()


class JobBusyError(RuntimeError):
    pass


def start_job(job_type: str, payload: dict[str, Any] | None = None) -> int:
    group = _group(job_type)

    def _create() -> int:
        with _START_LOCK:
            conn = connect()
            try:
                init_db(conn)
                repo = Repository(conn)
                if repo.active_job_in(group):
                    raise JobBusyError("A job of this type is already running.")
                return repo.create_job(job_type, payload)
            finally:
                conn.close()

    job_id = with_retry(_create)
    _EXECUTOR.submit(_execute, job_id)
    return job_id


def request_command(job_id: int, command: str) -> None:
    """Queue pause/resume/stop and reflect it in status immediately for the UI."""

    def _run() -> None:
        conn = connect()
        try:
            init_db(conn)
            repo = Repository(conn)
            job = repo.get_job(job_id)
            if not job:
                return
            current_status = str(job["status"])
            cmd = str(command or "").strip().lower()
            transition = apply_job_command(current_status, cmd)
            if transition is None:
                return
            next_status, message, next_command = transition
            repo.set_job_command(job_id, next_command)
            repo.append_job_log(job_id, f"{cmd.capitalize()} requested.")
            repo.set_job_status(job_id, next_status, message)
            if next_status in TERMINAL_JOB_STATUSES:
                repo.set_job_command(job_id, "")
        finally:
            conn.close()

    with_retry(_run)


def cancel_active_jobs(job_types: tuple[str, ...] | list[str]) -> int:
    """Force-cancel any active jobs in this group. Returns how many were cancelled."""

    def _run() -> int:
        conn = connect()
        try:
            init_db(conn)
            repo = Repository(conn)
            cancelled = 0
            while True:
                job = repo.active_job_in(list(job_types))
                if not job:
                    return cancelled
                repo.set_job_command(int(job["id"]), "stop")
                repo.append_job_log(int(job["id"]), "Force cancelled.")
                repo.set_job_status(int(job["id"]), "cancelled", "Stopped.")
                repo.set_job_command(int(job["id"]), "")
                cancelled += 1
        finally:
            conn.close()

    return with_retry(_run)


def _group(job_type: str) -> tuple[str, ...]:
    if job_type in IMPORT_TYPES:
        return IMPORT_TYPES
    return (job_type,)


def _execute(job_id: int) -> None:
    settings = get_settings()
    conn = connect(settings.database_path)
    try:
        init_db(conn)
        repo = Repository(conn)
        job = repo.get_job(job_id)
        if not job:
            return
        payload = json.loads(job["payload_json"] or "{}")
        repo.set_job_status(job_id, "running", "Starting…")
        repo.append_job_log(job_id, f"Started {job['job_type']}.")

        def log(msg: str) -> None:
            repo.append_job_log(job_id, msg)

        def should_continue() -> bool:
            return _wait_if_paused(repo, job_id)

        job_type = str(job["job_type"])
        if job_type == "import_library":
            _run_import_library(settings, repo, log, should_continue)
        elif job_type == "import_playlist":
            _run_import_playlist(settings, repo, payload, log, should_continue)
        elif job_type == "import_retry":
            _run_import_retry(settings, repo, log, should_continue)
        elif job_type == SMART_TYPE:
            _run_smart_assign(settings, repo, payload, log, should_continue)
        elif job_type == PUBLISH_TYPE:
            _run_publish(settings, repo, payload, log, should_continue)
        else:
            raise ValueError(f"Unknown job type: {job_type}")

        latest = repo.get_job(job_id)
        if latest and latest["status"] in ACTIVE_JOB_STATUSES:
            if latest["command"] == "stop":
                repo.set_job_status(job_id, "cancelled", "Stopped.")
                repo.append_job_log(job_id, "Stopped.")
            else:
                repo.set_job_status(job_id, "success", "Finished.")
                repo.append_job_log(job_id, "Finished.")
    except Exception as exc:  # noqa: BLE001
        err = safe_error_message(exc)
        logger.error("Job %s failed: %s", job_id, err)
        try:
            Repository(conn).set_job_error(job_id, err)
            Repository(conn).append_job_log(job_id, f"Error: {err}")
        except Exception:  # noqa: BLE001
            logger.exception("Could not record job failure")
    finally:
        conn.close()


def _wait_if_paused(repo: Repository, job_id: int) -> bool:
    while True:
        job = repo.get_job(job_id)
        if not job:
            return False
        status = str(job["status"] or "")
        if status not in ACTIVE_JOB_STATUSES:
            return False
        command = str(job["command"] or "")
        if command == "stop":
            return False
        if command == "resume":
            repo.set_job_command(job_id, "")
            if status == "paused":
                repo.set_job_status(job_id, "running", "Resumed.")
                repo.append_job_log(job_id, "Resumed.")
            return True
        if command == "pause" or status == "paused":
            if status != "paused":
                repo.set_job_status(job_id, "paused", "Paused.")
                repo.append_job_log(job_id, "Paused.")
            time.sleep(0.4)
            continue
        return True


def _services(settings, repo: Repository):
    client = build_default_adapter(settings)
    assignments = AssignmentService(repo)
    return (
        ImportService(repo, client),
        SmartAssignService(repo, assignments, LlmClient(settings)),
        RemoteApplyService(repo, client),
    )


def _run_import_library(settings, repo, log, should_continue) -> None:
    imports, _, _ = _services(settings, repo)
    summary = imports.import_library(progress=log, should_continue=should_continue)
    log(
        f"Import {summary.status}: {summary.succeeded} playlists, "
        f"{summary.unique_tracks_upserted} tracks."
    )
    if summary.status == "failed":
        raise RuntimeError(summary.playlists[0].error if summary.playlists else "Import failed.")


def _run_import_playlist(settings, repo, payload, log, should_continue) -> None:
    ref = str(payload.get("playlist_ref") or "").strip()
    if not ref:
        raise ValueError("Playlist URL or ID is required.")
    if not should_continue():
        return
    imports, _, _ = _services(settings, repo)
    summary = imports.import_playlist_ref(ref, progress=log)
    p = summary.playlists[0] if summary.playlists else None
    if p and p.status == "success":
        log(f"{p.title} ({p.tracks_imported} tracks)")
    elif p and p.error:
        raise RuntimeError(p.error)
    else:
        raise RuntimeError("Import failed.")


def _run_import_retry(settings, repo, log, should_continue) -> None:
    imports, _, _ = _services(settings, repo)
    summary = imports.retry_failed_playlists(progress=log, should_continue=should_continue)
    log(f"Retry {summary.status}: {summary.succeeded} playlists.")


def _run_smart_assign(settings, repo, payload, log, should_continue) -> None:
    mode = str(payload.get("mode") or "batch")
    batch_size = max(1, int(payload.get("batch_size") or 40))
    _, smart, _ = _services(settings, repo)
    while True:
        if not should_continue():
            return
        result = smart.run(
            batch_size=batch_size,
            progress=log,
            should_continue=should_continue,
        )
        if result.errors:
            raise RuntimeError(result.errors[0])
        if result.remaining == 0 or mode == "batch":
            return
        if not should_continue():
            return


def _run_publish(settings, repo, payload, log, should_continue) -> None:
    _, _, remote = _services(settings, repo)
    result = remote.apply(
        confirmed=True,
        retry_failed_only=bool(payload.get("retry_failed_only")),
        should_continue=should_continue,
        progress=log,
    )
    if result.errors:
        raise RuntimeError(result.errors[0])
    log(f"Published {result.succeeded}. Skipped {result.skipped}.")
