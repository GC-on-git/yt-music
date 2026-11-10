"""LLM bulk assignment in the background."""

from __future__ import annotations

import streamlit as st

from src.app_context import get_context
from src.models.state_machines import job_status_label
from src.services.job_runner import SMART_TYPE
from src.ui.common import continue_pipeline, page_header
from src.ui.jobs import render_job_panel, start_named_job

ctx = get_context()
page_header("Smart Assign", step="smart")

pending = ctx.repo.count_pending_smart_assign()
done = ctx.repo.count_smart_assigned()
selected = ctx.repo.selected_smart_assign_playlist_count()
destinations = ctx.repo.list_destinations()

c1, c2, c3, c4 = st.columns(4)
c1.metric("Pending smart assign", pending)
c2.metric("Already smart assigned", done)
c3.metric("Selected playlists", selected)
c4.metric("Designed playlists", len(destinations))

active = ctx.repo.active_job_in((SMART_TYPE,))
busy = active is not None
batch_size = st.number_input("Batch size", min_value=1, max_value=200, value=40, step=1)

if not ctx.settings.llm_api_key:
    st.info("Add LLM_API_KEY to .env.")
elif selected == 0:
    st.info("Select playlists first.")
else:
    if busy:
        st.caption(
            "A Smart Assign job is still active "
            f"({job_status_label(active['status'])}). Resume it, or Stop / Clear stuck job below, then assign again."
        )
    b1, b2 = st.columns(2)
    cannot_run = pending == 0 or busy
    if b1.button("Assign batch", type="primary", disabled=cannot_run):
        start_named_job(SMART_TYPE, {"mode": "batch", "batch_size": int(batch_size)})
        st.rerun()
    if b2.button("Assign remaining", disabled=cannot_run):
        start_named_job(SMART_TYPE, {"mode": "all", "batch_size": int(batch_size)})
        st.rerun()

render_job_panel((SMART_TYPE,), show_pause=True, key="smart_jobs")
continue_pipeline("smart")
