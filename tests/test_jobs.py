"""Background job persistence."""

from src.models.state_machines import ACTIVE_JOB_STATUSES, TERMINAL_JOB_STATUSES
from src.services.job_runner import _wait_if_paused, request_command
from tests.conftest import seed_source_playlist, seed_track


def test_create_and_log_job(repo) -> None:
    job_id = repo.create_job("smart_assign", {"mode": "batch"})
    repo.append_job_log(job_id, "hello")
    row = repo.get_job(job_id)
    assert row is not None
    assert row["status"] == "queued"
    assert "hello" in row["logs"]
    assert repo.active_job_in(("smart_assign",))["id"] == job_id
    repo.set_job_status(job_id, "success", "done")
    assert repo.active_job_in(("smart_assign",)) is None


def test_wait_if_paused_honors_stop(repo) -> None:
    job_id = repo.create_job("smart_assign")
    repo.set_job_status(job_id, "running")
    repo.set_job_command(job_id, "stop")
    assert _wait_if_paused(repo, job_id) is False


def test_wait_if_paused_clears_resume(repo) -> None:
    job_id = repo.create_job("smart_assign")
    repo.set_job_status(job_id, "paused", "Paused.")
    repo.set_job_command(job_id, "resume")
    assert _wait_if_paused(repo, job_id) is True
    row = repo.get_job(job_id)
    assert row is not None
    assert row["command"] == ""
    assert row["status"] == "running"


def test_request_command_updates_status_immediately(repo, monkeypatch) -> None:
    import src.services.job_runner as job_runner

    class _SharedConn:
        def __init__(self, conn) -> None:
            self._conn = conn

        def close(self) -> None:
            return None

        def __getattr__(self, name: str):
            return getattr(self._conn, name)

    job_id = repo.create_job("smart_assign")
    repo.set_job_status(job_id, "running", "Working")
    monkeypatch.setattr(job_runner, "connect", lambda: _SharedConn(repo.conn))
    monkeypatch.setattr(job_runner, "init_db", lambda conn: None)

    request_command(job_id, "pause")
    paused = repo.get_job(job_id)
    assert paused is not None
    assert paused["command"] == "pause"
    assert paused["status"] == "paused"

    request_command(job_id, "resume")
    resumed = repo.get_job(job_id)
    assert resumed is not None
    assert resumed["command"] == "resume"
    assert resumed["status"] == "running"

    request_command(job_id, "stop")
    stopped = repo.get_job(job_id)
    assert stopped is not None
    assert stopped["status"] == "cancelled"
    assert stopped["command"] == ""
    assert "Stopped" in str(stopped["message"] or "")
    assert repo.active_job_in(("smart_assign",)) is None


def test_terminal_job_not_active(repo) -> None:
    """Jobs in terminal states are never returned by active_job_in."""
    for status in sorted(TERMINAL_JOB_STATUSES):
        job_id = repo.create_job("smart_assign")
        repo.set_job_status(job_id, status, "done")
        assert repo.active_job_in(("smart_assign",)) is None


def test_request_command_noop_on_terminal(repo, monkeypatch) -> None:
    """Sending pause/resume/stop to a finished job does nothing."""
    import src.services.job_runner as job_runner

    class _SharedConn:
        def __init__(self, conn):
            self._conn = conn
        def close(self):
            return None
        def __getattr__(self, name):
            return getattr(self._conn, name)

    monkeypatch.setattr(job_runner, "connect", lambda: _SharedConn(repo.conn))
    monkeypatch.setattr(job_runner, "init_db", lambda conn: None)

    job_id = repo.create_job("smart_assign")
    repo.set_job_status(job_id, "success", "Finished.")
    request_command(job_id, "pause")
    assert repo.get_job(job_id)["status"] == "success"


def test_pending_still_requires_selected_playlist(repo) -> None:
    tid = seed_track(repo, title="Pump", artists="Gym Artist")
    seed_source_playlist(repo, track_ids=[tid], include_in_smart_assign=False)
    assert repo.count_pending_smart_assign() == 0
    seed_source_playlist(
        repo, playlist_id="PL2", title="Keep", track_ids=[tid], include_in_smart_assign=True
    )
    assert repo.count_pending_smart_assign() == 1
