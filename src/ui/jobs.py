"""Live background-job status for long-running pipeline steps."""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from src.app_context import get_context
from src.models.state_machines import ACTIVE_JOB_STATUSES, job_status_label
from src.services.job_runner import (
    JobBusyError,
    cancel_active_jobs,
    request_command,
    start_job,
)


def start_named_job(job_type: str, payload: dict | None = None) -> None:
    try:
        start_job(job_type, payload)
    except JobBusyError as exc:
        st.warning(str(exc))
    except Exception as exc:  # noqa: BLE001
        text = str(exc)
        if "database is locked" in text.lower():
            st.warning(
                "Database is busy (another import/publish or page refresh held a lock). "
                "Wait a few seconds and try again."
            )
            return
        raise


def _pause_job(job_id: int) -> None:
    request_command(job_id, "pause")


def _resume_job(job_id: int) -> None:
    request_command(job_id, "resume")


def _stop_job(job_id: int) -> None:
    request_command(job_id, "stop")
    # Assign buttons live outside this fragment; refresh the whole page.
    st.rerun()


def _clear_jobs(job_types: list[str]) -> None:
    cancel_active_jobs(job_types)
    st.rerun()


def render_job_panel(
    job_types: Sequence[str], *, show_pause: bool = False, key: str = "job_panel"
) -> str | None:
    """Show the latest job in this group. Returns current status or None."""

    types = list(job_types)

    @st.fragment(run_every="2s", key=key)
    def _panel() -> str | None:
        ctx = get_context()
        job = ctx.repo.latest_job_in(types)
        if not job:
            st.caption("No activity yet.")
            return None
        job_id = int(job["id"])
        status = str(job["status"])
        if status == "running":
            st.info(job["message"] or "Running…")
        elif status == "paused":
            st.warning(job["message"] or "Paused.")
        elif status == "success":
            st.success(job["message"] or "Finished.")
        elif status in {"failed", "cancelled"}:
            st.error(job["error"] or job["message"] or status)
        else:
            st.caption(job["message"] or status)

        if status in ACTIVE_JOB_STATUSES:
            if show_pause:
                st.caption("Pause waits after the current LLM reply. Stop cancels now and unlocks Assign.")
            cols = st.columns(3 if show_pause else 1)
            if show_pause:
                cols[0].button(
                    "Pause",
                    disabled=status == "paused",
                    key=f"job_pause_{job_id}",
                    on_click=_pause_job,
                    args=(job_id,),
                )
                cols[1].button(
                    "Resume",
                    disabled=status != "paused",
                    key=f"job_resume_{job_id}",
                    on_click=_resume_job,
                    args=(job_id,),
                )
                stop_col = cols[2]
            else:
                stop_col = cols[0]
            stop_col.button(
                "Stop",
                key=f"job_stop_{job_id}",
                on_click=_stop_job,
                args=(job_id,),
            )
            if status == "paused":
                st.button(
                    "Clear stuck job",
                    key=f"job_clear_{job_id}",
                    help="Use if the worker died while paused and Assign stays locked.",
                    on_click=_clear_jobs,
                    args=(types,),
                )

        logs = str(job["logs"] or "").strip() or "No activity yet."
        st.text_area("Activity", logs, height=260, disabled=True, label_visibility="collapsed")
        return status

    return _panel()
