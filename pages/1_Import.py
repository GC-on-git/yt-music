"""Import playlists in the background."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app_context import get_context
from src.services.job_runner import IMPORT_TYPES
from src.ui.common import continue_pipeline, page_header, show_auth_banner
from src.ui.jobs import render_job_panel, start_named_job

ctx = get_context()
page_header("Import", step="import")
show_auth_banner()
st.caption(
    "Imports YouTube Music playlists and music tracks only. "
    "Skips Watch Later, Liked videos, uploads, and non-music videos. "
    "Use music.youtube.com links for single-playlist import."
)

busy = ctx.repo.active_job_in(IMPORT_TYPES) is not None
col_a, col_b = st.columns(2, vertical_alignment="bottom")
with col_a:
    if st.button(
        "Import library",
        type="primary",
        disabled=not ctx.client.is_authenticated() or busy,
    ):
        start_named_job("import_library")
        st.rerun()
    if st.button("Retry failed", disabled=busy):
        start_named_job("import_retry")
        st.rerun()

with col_b:
    ref = st.text_input("YouTube Music playlist URL or ID")
    if st.button("Import playlist", disabled=busy):
        if not ref.strip():
            st.error("Enter a music.youtube.com playlist URL or ID.")
        else:
            start_named_job("import_playlist", {"playlist_ref": ref.strip()})
            st.rerun()

render_job_panel(IMPORT_TYPES, key="import_jobs")

playlists = ctx.repo.list_source_playlists()
if playlists:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "playlist": r["title"],
                    "tracks": r["local_track_count"],
                    "status": r["import_status"],
                    "privacy": r["privacy"],
                }
                for r in playlists
            ]
        ),
        width="stretch",
        hide_index=True,
    )
    options = {str(r["title"]): int(r["id"]) for r in playlists}
    choice = st.selectbox("Tracks", list(options.keys()))
    items = ctx.repo.list_playlist_items(options[choice])
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "title": i["title"],
                    "artists": i["artists"],
                    "album": i["album"],
                    "duration": i["duration_text"],
                }
                for i in items
            ]
        ),
        width="stretch",
        hide_index=True,
    )

continue_pipeline("import", disabled=len(playlists) == 0)
