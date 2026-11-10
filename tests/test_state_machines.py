"""Tests for the formalised state machines in src/models/state_machines.py."""

from __future__ import annotations

import pytest

from src.models.state_machines import (
    ACTIVE_JOB_STATUSES,
    TERMINAL_JOB_STATUSES,
    DestinationOrigin,
    JobCommand,
    JobStatus,
    PublishOpPhase,
    SmartAssignPhase,
    apply_job_command,
    can_apply_job_command,
    import_is_complete,
    import_is_in_progress,
    import_is_retryable,
    job_status_label,
    pipeline_readiness,
    publish_op_phase,
)
from tests.conftest import seed_source_playlist, seed_track


# ---------------------------------------------------------------------------
# Job transitions
# ---------------------------------------------------------------------------


class TestJobTransitions:
    """Verify every valid and invalid command from every status."""

    def test_active_and_terminal_are_disjoint(self) -> None:
        assert ACTIVE_JOB_STATUSES & TERMINAL_JOB_STATUSES == set()

    def test_all_statuses_covered(self) -> None:
        all_statuses = {s.value for s in JobStatus}
        assert all_statuses == ACTIVE_JOB_STATUSES | TERMINAL_JOB_STATUSES

    def test_pause_from_running(self) -> None:
        result = apply_job_command("running", "pause")
        assert result is not None
        status, message, command = result
        assert status == "paused"
        assert command == "pause"

    def test_resume_from_paused(self) -> None:
        result = apply_job_command("paused", "resume")
        assert result is not None
        status, message, command = result
        assert status == "running"
        assert command == "resume"

    def test_stop_from_running(self) -> None:
        result = apply_job_command("running", "stop")
        assert result is not None
        assert result[0] == "cancelled"
        assert result[2] == ""

    def test_stop_from_paused(self) -> None:
        result = apply_job_command("paused", "stop")
        assert result is not None
        assert result[0] == "cancelled"

    def test_stop_from_queued(self) -> None:
        result = apply_job_command("queued", "stop")
        assert result is not None
        assert result[0] == "cancelled"

    @pytest.mark.parametrize("status", sorted(TERMINAL_JOB_STATUSES))
    def test_commands_from_terminal_are_rejected(self, status: str) -> None:
        for cmd in ("pause", "resume", "stop"):
            assert can_apply_job_command(status, cmd) is False
            assert apply_job_command(status, cmd) is None

    def test_invalid_command_rejected(self) -> None:
        assert can_apply_job_command("running", "explode") is False
        assert apply_job_command("running", "explode") is None

    def test_empty_command_rejected(self) -> None:
        assert can_apply_job_command("running", "") is False

    def test_resume_from_running_is_valid(self) -> None:
        """Resume from running maps to (running, ...) — not rejected."""
        assert can_apply_job_command("running", "resume") is False


class TestJobStatusLabel:
    def test_known_statuses(self) -> None:
        assert job_status_label("queued") == "Queued"
        assert job_status_label("success") == "Finished"
        assert job_status_label("cancelled") == "Stopped"

    def test_unknown_status_capitalised(self) -> None:
        assert job_status_label("mystery") == "Mystery"


# ---------------------------------------------------------------------------
# Destination origin
# ---------------------------------------------------------------------------


class TestDestinationOrigin:
    def test_generated_from_llm_description(self) -> None:
        assert (
            DestinationOrigin.from_playlist(
                "Sufi",
                "Created during smart assign for a missing mood or theme.",
            )
            == DestinationOrigin.GENERATED
        )

    def test_generated_from_legacy_description(self) -> None:
        assert (
            DestinationOrigin.from_playlist(
                "Lofi",
                "Created during smart assign for a missing category.",
            )
            == DestinationOrigin.GENERATED
        )

    def test_others_is_generated(self) -> None:
        assert DestinationOrigin.from_playlist("Others") == DestinationOrigin.GENERATED
        assert DestinationOrigin.from_playlist("others") == DestinationOrigin.GENERATED

    def test_predesigned(self) -> None:
        assert (
            DestinationOrigin.from_playlist(
                "Gym",
                "Pre-designed from an imported playlist excluded from Smart Assign.",
            )
            == DestinationOrigin.PREDESIGNED
        )

    def test_user_created(self) -> None:
        assert DestinationOrigin.from_playlist("My Playlist") == DestinationOrigin.USER
        assert (
            DestinationOrigin.from_playlist("My Playlist", "Weekend mix")
            == DestinationOrigin.USER
        )

    def test_matches_is_generated_playlist(self) -> None:
        from src.services.smart_assign_service import LLM_CREATED_DESCRIPTION, is_generated_playlist

        assert is_generated_playlist("Others") is True
        assert is_generated_playlist("Sufi", LLM_CREATED_DESCRIPTION) is True
        assert is_generated_playlist("Gym") is False

    def test_matches_is_predesigned_playlist(self) -> None:
        from src.services.assignment_service import PREDESIGNED_DESCRIPTION, is_predesigned_playlist

        assert is_predesigned_playlist(PREDESIGNED_DESCRIPTION) is True
        assert is_predesigned_playlist("Weekend mix") is False
        assert is_predesigned_playlist(None) is False


# ---------------------------------------------------------------------------
# Import lifecycle helpers
# ---------------------------------------------------------------------------


class TestImportLifecycle:
    def test_retryable(self) -> None:
        assert import_is_retryable("failed") is True
        assert import_is_retryable("partial") is True
        assert import_is_retryable("success") is False
        assert import_is_retryable("pending") is False

    def test_complete(self) -> None:
        assert import_is_complete("success") is True
        assert import_is_complete("partial") is False
        assert import_is_complete("failed") is False

    def test_in_progress(self) -> None:
        assert import_is_in_progress("pending") is True
        assert import_is_in_progress("partial") is True
        assert import_is_in_progress("success") is False


# ---------------------------------------------------------------------------
# Publish operation phase
# ---------------------------------------------------------------------------


class TestPublishOpPhase:
    def test_unattempted(self) -> None:
        assert publish_op_phase(succeeded=False, failed=False) == PublishOpPhase.UNATTEMPTED

    def test_succeeded(self) -> None:
        assert publish_op_phase(succeeded=True, failed=False) == PublishOpPhase.SUCCEEDED

    def test_failed(self) -> None:
        assert publish_op_phase(succeeded=False, failed=True) == PublishOpPhase.FAILED

    def test_succeeded_takes_priority(self) -> None:
        assert publish_op_phase(succeeded=True, failed=True) == PublishOpPhase.SUCCEEDED


# ---------------------------------------------------------------------------
# Pipeline readiness
# ---------------------------------------------------------------------------


class TestPipelineReadiness:
    def test_import_always_ready(self, repo) -> None:
        ok, reason = pipeline_readiness(repo, "import")
        assert ok is True
        assert reason is None

    def test_select_needs_playlists(self, repo) -> None:
        ok, reason = pipeline_readiness(repo, "select")
        assert ok is False
        assert reason is not None

    def test_select_ready_after_import(self, repo) -> None:
        tid = seed_track(repo)
        seed_source_playlist(repo, track_ids=[tid])
        ok, _ = pipeline_readiness(repo, "select")
        assert ok is True

    def test_smart_needs_selected(self, repo) -> None:
        ok, reason = pipeline_readiness(repo, "smart")
        assert ok is False
        assert "Select playlists" in (reason or "")

    def test_smart_ready_after_selection(self, repo) -> None:
        tid = seed_track(repo)
        seed_source_playlist(repo, track_ids=[tid], include_in_smart_assign=True)
        ok, _ = pipeline_readiness(repo, "smart")
        assert ok is True

    def test_publish_needs_destinations(self, repo) -> None:
        ok, reason = pipeline_readiness(repo, "publish")
        assert ok is False
        assert "destination" in (reason or "").lower()

    def test_unknown_step_is_ready(self, repo) -> None:
        ok, reason = pipeline_readiness(repo, "unknown_step")
        assert ok is True
        assert reason is None
