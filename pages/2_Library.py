"""Searchable track library."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app_context import get_context
from src.services.assignment_service import labeled_track_map
from src.ui.common import format_duration, page_header

ctx = get_context()
page_header("Library")

sources = ctx.repo.list_source_playlists()
destinations = ctx.repo.list_destinations()

with st.form("filters"):
    c1, c2, c3, c4 = st.columns(4)
    search = c1.text_input("Search")
    artist = c2.text_input("Artist")
    album = c3.text_input("Album")
    assignment = c4.selectbox("Status", ["", "assigned", "unassigned"])
    source_options = {"": None, **{r["title"]: int(r["id"]) for r in sources}}
    dest_options = {"": None, **{d.name: d.id for d in destinations}}
    c5, c6, c7 = st.columns(3)
    source_sel = c5.selectbox("From playlist", list(source_options.keys()))
    dest_sel = c6.selectbox("In playlist", list(dest_options.keys()))
    page_size = c7.selectbox("Page size", [25, 50, 100, 200], index=1)
    submitted = st.form_submit_button("Filter")

if "cat_page" not in st.session_state:
    st.session_state.cat_page = 0
if submitted:
    st.session_state.cat_page = 0

page = st.session_state.cat_page
rows, total = ctx.repo.catalogue_query(
    search=search or None,
    artist=artist or None,
    album=album or None,
    source_playlist_id=source_options[source_sel],
    destination_playlist_id=dest_options[dest_sel],
    assignment_filter=assignment or None,
    limit=page_size,
    offset=page * page_size,
)

st.caption(f"{len(rows)} of {total}")
nav1, nav2, _ = st.columns([1, 1, 6])
if nav1.button("Previous", disabled=page <= 0):
    st.session_state.cat_page = max(0, page - 1)
    st.rerun()
if nav2.button("Next", disabled=(page + 1) * page_size >= total):
    st.session_state.cat_page = page + 1
    st.rerun()

if rows:
    st.dataframe(
        pd.DataFrame(
            [
                {
                    "title": r["title"],
                    "artists": r["artists"],
                    "album": r["album"],
                    "duration": format_duration(r["duration_seconds"], r["duration_text"]),
                    "playlists": r["destination_memberships"],
                    "from": r["source_memberships"],
                }
                for r in rows
            ]
        ),
        width="stretch",
        hide_index=True,
    )

    mapping = labeled_track_map(rows)
    selected = st.multiselect("Assign", list(mapping.keys()))
    dest_name = st.selectbox("To", [d.name for d in destinations] if destinations else [])
    if destinations and st.button("Assign selected", type="primary") and selected:
        dest_id = next(d.id for d in destinations if d.name == dest_name)
        ctx.assignments.assign_labels(selected, mapping, dest_id)
        st.rerun()
