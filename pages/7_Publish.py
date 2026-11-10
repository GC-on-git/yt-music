"""Create destination playlists on YouTube in the background."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app_context import get_context
from src.services.job_runner import PUBLISH_TYPE
from src.ui.common import page_header, show_auth_banner
from src.ui.jobs import render_job_panel, start_named_job

ctx = get_context()
page_header("Publish", step="publish")
show_auth_banner()

previews = ctx.remote.preview()
if not previews:
    st.info("Nothing to publish.")
else:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "action": p.operation_type.value.replace("_", " "),
                    "playlist": p.destination_name,
                    "track": p.track_title or "",
                }
                for p in previews
            ]
        ),
        width="stretch",
        hide_index=True,
    )

confirm = st.checkbox("Create and fill destination playlists only. Source playlists stay unchanged.")
retry_only = st.checkbox("Retry failed only")
busy = ctx.repo.active_job_in((PUBLISH_TYPE,)) is not None
if st.button("Publish", type="primary", disabled=not confirm or not previews or busy):
    start_named_job(PUBLISH_TYPE, {"retry_failed_only": retry_only})
    st.rerun()

render_job_panel((PUBLISH_TYPE,), key="publish_jobs")
