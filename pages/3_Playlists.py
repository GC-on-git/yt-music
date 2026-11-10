"""Destination playlists."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app_context import get_context
from src.ui.common import continue_pipeline, page_header, track_select_options

ctx = get_context()
page_header("Design playlists", step="design")

destinations = ctx.repo.list_destinations()

c1, c2 = st.columns(2)
with c1:
    name = st.text_input("Name")
    description = st.text_input("Description")
    if st.button("Create", type="primary"):
        try:
            ctx.assignments.create_destination(name, description or None)
            st.rerun()
        except Exception as exc:  # noqa: BLE001
            st.error(str(exc))

with c2:
    search = st.text_input("Find track")
    mapping = track_select_options(search)
    labels = list(mapping.keys())
    track_choice = st.selectbox("Track", labels if labels else ["—"])
    dest_names = [d.name for d in destinations]
    dest_choice = st.selectbox("Playlist", dest_names if dest_names else ["—"])
    action = st.selectbox("Action", ["Add to playlist", "Remove from playlist", "Clear all playlists"])
    if st.button("Apply") and destinations and labels:
        dest = next(d for d in destinations if d.name == dest_choice)
        track_id = mapping[track_choice]
        if action == "Add to playlist":
            ctx.assignments.assign(track_id, dest.id)
        elif action == "Remove from playlist":
            ctx.assignments.unassign(track_id, dest.id)
        else:
            ctx.assignments.unassign(track_id, None)
        st.rerun()
    if st.button("Undo"):
        ctx.assignments.undo()
        st.rerun()

for d in destinations:
    tracks = ctx.repo.destination_tracks(d.id)
    with st.expander(f"{d.name} ({len(tracks)})"):
        new_name = st.text_input("Name", value=d.name, key=f"rename_{d.id}")
        new_description = st.text_area(
            "Description",
            value=d.description or "",
            key=f"desc_{d.id}",
        )
        b1, b2 = st.columns(2)
        if b1.button("Save", key=f"save_{d.id}"):
            try:
                ctx.assignments.update_destination(
                    d.id,
                    name=new_name,
                    description=new_description,
                    set_description=True,
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if b2.button("Delete", key=f"del_{d.id}"):
            ctx.assignments.delete_destination(d.id)
            st.rerun()
        if tracks:
            st.dataframe(
                pd.DataFrame(
                    [{"title": t["title"], "artists": t["artists"]} for t in tracks]
                ),
                width="stretch",
                hide_index=True,
                alt=f"Tracks in {d.name}",
            )

continue_pipeline("design")
