"""Explicit state machines for the YT Music Organizer.

Centralises enums, allowed transitions, and derived-phase helpers that were
previously scattered as ad-hoc string literals across services, UI, and the
repository layer.  **No DB schema changes** — stored values stay the same
strings; this module only provides typed wrappers and transition rules.

State machines formalised here
------------------------------
- Background jobs: ``JobStatus`` x ``JobCommand``
- Smart-assign track eligibility: ``SmartAssignPhase``
- Import lifecycle: helpers on ``ImportStatus``
- Publish operation idempotency: ``PublishOpPhase``
- Destination origin taxonomy: ``DestinationOrigin``
- Pipeline step readiness: ``pipeline_readiness``
"""

from __future__ import annotations

from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.db.repository import Repository


# ---------------------------------------------------------------------------
# Background jobs
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    SUCCESS = "success"
    FAILED = "failed"
    CANCELLED = "cancelled"


class JobCommand(str, Enum):
    PAUSE = "pause"
    RESUME = "resume"
    STOP = "stop"
    NONE = ""


ACTIVE_JOB_STATUSES: frozenset[str] = frozenset({
    JobStatus.QUEUED.value,
    JobStatus.RUNNING.value,
    JobStatus.PAUSED.value,
})

TERMINAL_JOB_STATUSES: frozenset[str] = frozenset({
    JobStatus.SUCCESS.value,
    JobStatus.FAILED.value,
    JobStatus.CANCELLED.value,
})

_JOB_TRANSITIONS: dict[tuple[str, str], tuple[str, str, str]] = {
    # (current_status, command) -> (next_status, ui_message, next_command)
    (JobStatus.RUNNING.value, JobCommand.PAUSE.value): (
        JobStatus.PAUSED.value,
        "Paused. Waiting for the current LLM call to finish\u2026",
        JobCommand.PAUSE.value,
    ),
    (JobStatus.PAUSED.value, JobCommand.RESUME.value): (
        JobStatus.RUNNING.value,
        "Resuming\u2026",
        JobCommand.RESUME.value,
    ),
    (JobStatus.QUEUED.value, JobCommand.PAUSE.value): (
        JobStatus.PAUSED.value,
        "Paused. Waiting for the current LLM call to finish\u2026",
        JobCommand.PAUSE.value,
    ),
    (JobStatus.QUEUED.value, JobCommand.RESUME.value): (
        JobStatus.RUNNING.value,
        "Resuming\u2026",
        JobCommand.RESUME.value,
    ),
}

# Stop is special: it applies from any active status and clears the command.
_STOP_RESULT = (JobStatus.CANCELLED.value, "Stopped.", JobCommand.NONE.value)


def can_apply_job_command(status: str, command: str) -> bool:
    """Whether *command* is valid for the current *status*."""
    if status not in ACTIVE_JOB_STATUSES:
        return False
    command = (command or "").strip().lower()
    if command not in {c.value for c in JobCommand if c != JobCommand.NONE}:
        return False
    if command == JobCommand.STOP.value:
        return True
    return (status, command) in _JOB_TRANSITIONS


def apply_job_command(
    status: str, command: str
) -> tuple[str, str, str] | None:
    """Return ``(next_status, ui_message, next_command)`` or ``None`` if invalid.

    The caller is still responsible for writing to the DB — this is pure logic.
    """
    if not can_apply_job_command(status, command):
        return None
    command = (command or "").strip().lower()
    if command == JobCommand.STOP.value:
        return _STOP_RESULT
    return _JOB_TRANSITIONS[(status, command)]


def job_status_label(status: str) -> str:
    """Human-readable label for use in the UI."""
    labels = {
        JobStatus.QUEUED.value: "Queued",
        JobStatus.RUNNING.value: "Running",
        JobStatus.PAUSED.value: "Paused",
        JobStatus.SUCCESS.value: "Finished",
        JobStatus.FAILED.value: "Failed",
        JobStatus.CANCELLED.value: "Stopped",
    }
    return labels.get(status, status.capitalize())


# ---------------------------------------------------------------------------
# Smart-assign track eligibility (derived phases)
# ---------------------------------------------------------------------------

class SmartAssignPhase(str, Enum):
    """Conceptual phase of a track in the smart-assign pipeline.

    The authoritative source for the ``PENDING`` set is the SQL predicate
    ``_SMART_PENDING_WHERE`` in ``repository.py``.  This enum documents
    the *intent* so that UI copy and tests can speak the same language.
    """
    OWN_UPLOAD = "own_upload"
    EXCLUDED_SOURCE = "excluded_source"
    MANUALLY_ASSIGNED = "manually_assigned"
    SMART_ASSIGNED = "smart_assigned"
    PENDING = "pending"


# ---------------------------------------------------------------------------
# Import lifecycle helpers (wraps existing ImportStatus values)
# ---------------------------------------------------------------------------

def import_is_retryable(status: str) -> bool:
    """A playlist/run with this status can be retried."""
    return status in {"failed", "partial"}


def import_is_complete(status: str) -> bool:
    return status == "success"


def import_is_in_progress(status: str) -> bool:
    """True only while an import is actively running (checkpoint partial)."""
    return status in {"pending", "partial"}


# ---------------------------------------------------------------------------
# Publish operation idempotency
# ---------------------------------------------------------------------------

class PublishOpPhase(str, Enum):
    UNATTEMPTED = "unattempted"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


def publish_op_phase(*, succeeded: bool, failed: bool) -> PublishOpPhase:
    """Derive the phase from ``repo.operation_succeeded`` / ``operation_failed``."""
    if succeeded:
        return PublishOpPhase.SUCCEEDED
    if failed:
        return PublishOpPhase.FAILED
    return PublishOpPhase.UNATTEMPTED


# ---------------------------------------------------------------------------
# Destination origin taxonomy
# ---------------------------------------------------------------------------

_PREDESIGNED_DESCRIPTION = (
    "Pre-designed from an imported playlist excluded from Smart Assign."
)

_GENERATED_DESCRIPTIONS: frozenset[str] = frozenset({
    "Created during smart assign for a missing mood or theme.",
    "Created during smart assign for a missing category.",
})

_OTHERS_NAME = "others"


class DestinationOrigin(str, Enum):
    GENERATED = "Generated"
    PREDESIGNED = "Imported"
    USER = "Yours"

    @classmethod
    def from_playlist(cls, name: str, description: str | None = None) -> DestinationOrigin:
        if str(name or "").strip().lower() == _OTHERS_NAME:
            return cls.GENERATED
        desc = (description or "").strip()
        if desc in _GENERATED_DESCRIPTIONS:
            return cls.GENERATED
        if desc == _PREDESIGNED_DESCRIPTION:
            return cls.PREDESIGNED
        return cls.USER


# ---------------------------------------------------------------------------
# Pipeline step readiness
# ---------------------------------------------------------------------------

_PIPELINE_STEPS = (
    "import", "select", "design", "smart", "organize", "review", "publish",
)


def pipeline_readiness(repo: Repository, step: str) -> tuple[bool, str | None]:
    """Soft gate: ``(ok, reason)``  —  never blocks navigation, only captions."""
    if step == "select":
        if not repo.list_source_playlists():
            return False, "Import playlists first."
    elif step == "design":
        if not repo.list_source_playlists():
            return False, "Import and select playlists first."
    elif step == "smart":
        if repo.selected_smart_assign_playlist_count() == 0:
            return False, "Select playlists for Smart Assign first."
    elif step == "organize":
        if not repo.list_destinations():
            return False, "Design playlists or run Smart Assign first."
    elif step == "review":
        if not repo.list_destinations():
            return False, "No playlists to review yet."
    elif step == "publish":
        if not repo.list_destinations():
            return False, "Create destination playlists before publishing."
    return True, None
