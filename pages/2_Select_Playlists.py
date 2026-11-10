"""Choose which imported playlists Smart Assign may use."""

from __future__ import annotations

import streamlit as st

from src.app_context import get_context
from src.ui.common import continue_pipeline, page_header, source_playlist_picker

ctx = get_context()
page_header("Select playlists", step="select")

sources = ctx.repo.list_source_playlists()
if not sources:
    continue_pipeline("select", disabled=True)
else:
    st.caption(
        "Selected rows go to Smart Assign. Unselected imported playlists become "
        "pre-designed destinations (name + tracks) that Smart Assign can reuse."
    )
    selected = source_playlist_picker(key_prefix="src_smart")
    sync = ctx.assignments.sync_predesigned_from_excluded_sources()
    if sync["excluded"]:
        st.caption(
            f"Pre-designed from excluded imports: {sync['excluded']} playlists "
            f"({sync['created']} new, {sync['assigned']} track links this sync)."
        )
    continue_pipeline("select", disabled=selected == 0)
