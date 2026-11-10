"""Merge similar destination playlists and edit names or descriptions."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app_context import get_context
from src.models.state_machines import DestinationOrigin
from src.ui.common import continue_pipeline, page_header


def _origin_label(name: str, description: str | None) -> str:
    return DestinationOrigin.from_playlist(name, description).value

ctx = get_context()
page_header("Organize playlists", step="organize")
st.caption(
    "After Smart Assign, merge similar playlists and clean up names or descriptions before Review."
)

destinations = ctx.repo.list_destinations()
counts = ctx.repo.destination_track_counts()

if not destinations:
    st.info("No destination playlists yet. Design playlists or run Smart Assign first.")
    continue_pipeline("organize", disabled=True)
    st.stop()

overview = pd.DataFrame(
    [
        {
            "playlist": dest.name,
            "tracks": counts.get(dest.id, 0),
            "description": dest.description or "",
            "origin": _origin_label(dest.name, dest.description),
        }
        for dest in destinations
    ]
)
st.dataframe(
    overview,
    width="stretch",
    hide_index=True,
    alt="Destination playlists after Smart Assign",
    column_config={
        "playlist": st.column_config.TextColumn("Playlist", pinned=True),
        "tracks": st.column_config.NumberColumn("Tracks"),
        "description": st.column_config.TextColumn("Description"),
        "origin": st.column_config.TextColumn("Origin"),
    },
)

st.subheader("Merge similar playlists")
name_to_id = {dest.name: dest.id for dest in destinations}
merge_names = st.multiselect(
    "Playlists to merge",
    list(name_to_id.keys()),
    key="organize_merge_names",
)
keep_options = merge_names if len(merge_names) >= 2 else list(name_to_id.keys())
keep_name = st.selectbox(
    "Keep as",
    keep_options,
    key="organize_keep_name",
    disabled=len(merge_names) < 2,
)
keep_dest = next((dest for dest in destinations if dest.name == keep_name), None)
merged_name = st.text_input(
    "Merged name",
    value=keep_dest.name if keep_dest else "",
    key="organize_merged_name",
    disabled=len(merge_names) < 2,
)
merged_description = st.text_area(
    "Merged description",
    value=(keep_dest.description or "") if keep_dest else "",
    key="organize_merged_description",
    disabled=len(merge_names) < 2,
)
if st.button("Merge", type="primary", disabled=len(merge_names) < 2 or keep_dest is None):
    try:
        assert keep_dest is not None
        source_ids = [name_to_id[name] for name in merge_names]
        moved = ctx.assignments.merge_destinations(
            source_ids,
            keep_dest.id,
            name=merged_name,
            description=merged_description,
            set_description=True,
        )
        st.success(f"Merged into {merged_name.strip() or keep_dest.name}. Moved {moved} track links.")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

st.subheader("Edit playlists")
for dest in destinations:
    track_count = counts.get(dest.id, 0)
    origin = _origin_label(dest.name, dest.description)
    with st.expander(f"{dest.name} ({track_count}) · {origin}"):
        new_name = st.text_input("Name", value=dest.name, key=f"organize_name_{dest.id}")
        new_description = st.text_area(
            "Description",
            value=dest.description or "",
            key=f"organize_desc_{dest.id}",
        )
        tracks = ctx.repo.destination_tracks(dest.id)
        if tracks:
            st.dataframe(
                pd.DataFrame(
                    [{"title": track["title"], "artists": track["artists"]} for track in tracks]
                ),
                width="stretch",
                hide_index=True,
                alt=f"Tracks in {dest.name}",
            )
        save_c, delete_c = st.columns(2)
        if save_c.button("Save", key=f"organize_save_{dest.id}"):
            try:
                ctx.assignments.update_destination(
                    dest.id,
                    name=new_name,
                    description=new_description,
                    set_description=True,
                )
                st.rerun()
            except Exception as exc:  # noqa: BLE001
                st.error(str(exc))
        if delete_c.button("Delete", key=f"organize_del_{dest.id}"):
            ctx.assignments.delete_destination(dest.id)
            st.rerun()

continue_pipeline("organize")
