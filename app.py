"""Pipeline entrypoint."""

from __future__ import annotations

import streamlit as st

from src.app_context import get_context
from src.ui.common import PIPELINE, page_header, show_auth_banner

st.set_page_config(
    page_title="YT Music",
    page_icon=":material/library_music:",
    layout="wide",
    initial_sidebar_state="expanded",
)


def home() -> None:
    ctx = get_context()
    page_header("Home")
    show_auth_banner()
    stats = ctx.repo.dashboard_stats()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Playlists", stats.source_playlists)
    c2.metric("Tracks", stats.unique_tracks)
    c3.metric("Assigned", stats.assigned_tracks)
    c4.metric("Unassigned", stats.unassigned_tracks)
    start_c, setup_c = st.columns(2)
    if start_c.button("Start", type="primary"):
        st.switch_page(PIPELINE[0][2])
    if setup_c.button("Setup"):
        st.switch_page("pages/0_Setup.py")


page = st.navigation(
    {
        "": [
            st.Page(home, title="Home", icon=":material/home:", default=True),
            st.Page("pages/0_Setup.py", title="Setup", icon=":material/settings:"),
        ],
        "Pipeline": [
            st.Page("pages/1_Import.py", title="Import", icon=":material/cloud_download:"),
            st.Page(
                "pages/2_Select_Playlists.py",
                title="Select playlists",
                icon=":material/checklist:",
            ),
            st.Page(
                "pages/3_Playlists.py",
                title="Design playlists",
                icon=":material/queue_music:",
            ),
            st.Page(
                "pages/4_Smart_Assign.py",
                title="Smart Assign",
                icon=":material/auto_awesome:",
            ),
            st.Page(
                "pages/5_Organize_Playlists.py",
                title="Organize playlists",
                icon=":material/merge:",
            ),
            st.Page("pages/5_Review.py", title="Review", icon=":material/rate_review:"),
            st.Page("pages/7_Publish.py", title="Publish", icon=":material/publish:"),
        ],
        "Tools": [
            st.Page("pages/2_Library.py", title="Library", icon=":material/library_music:"),
            st.Page("pages/6_Export.py", title="Export", icon=":material/ios_share:"),
        ],
    },
    position="sidebar",
)
page.run()
