"""Pick a playlist, then review one song at a time."""

from __future__ import annotations

from html import escape

import streamlit as st

from src.app_context import get_context
from src.services.smart_assign_service import is_generated_playlist
from src.ui.common import continue_pipeline, format_duration, page_header
from src.ui.review_state import (
    SCOPE_UNASSIGNED,
    close_scope,
    ensure_track_index,
    get_scope,
    open_scope,
    set_track,
)

ctx = get_context()
page_header("Review", step="review")


def _pick_button(label: str, count: int, key: str, scope: str | int) -> None:
    if st.button(f"{label} ({count})", key=key, width="stretch"):
        open_scope(scope)


destinations = ctx.repo.list_destinations()
counts = ctx.repo.destination_track_counts()
generated = [d for d in destinations if is_generated_playlist(d.name, d.description)]
user_playlists = [d for d in destinations if d not in generated]
scope = get_scope()

if scope is None:
    with st.container(key="review_pick"):
        _pick_button("Unsorted", ctx.repo.count_unassigned_tracks(), "rev_scope_unassigned", SCOPE_UNASSIGNED)
        for dest in generated:
            _pick_button(dest.name, counts.get(dest.id, 0), f"rev_scope_{dest.id}", dest.id)
        for dest in user_playlists:
            _pick_button(dest.name, counts.get(dest.id, 0), f"rev_scope_{dest.id}", dest.id)
    continue_pipeline("review")
    st.stop()

if scope != SCOPE_UNASSIGNED:
    selected = next((d for d in destinations if d.id == scope), None)
    if selected is None:
        close_scope()
        st.stop()
    scope_title = selected.name
    rows = ctx.repo.assigned_tracks_for_review(destination_id=int(scope))
else:
    scope_title = "Unsorted"
    rows = ctx.repo.assigned_tracks_for_review(unassigned_only=True)

with st.container(key="review_back"):
    back, title = st.columns([0.12, 0.88], vertical_alignment="center")
    with back:
        if st.button("←", help="Playlists"):
            close_scope()
    with title:
        st.subheader(scope_title)

if not rows:
    st.info("No tracks in this playlist.")
    st.stop()

ids = [int(r["id"]) for r in rows]
current_id, index = ensure_track_index(ids)
track = rows[index]
assigned_names = [
    part.strip()
    for part in str(track["destination_memberships"] or "").split("|")
    if part.strip()
]

song_area, playlists = st.columns([0.66, 0.34])

with song_area:
    with st.container(key="review_arrows"):
        left, card, right = st.columns([0.12, 0.76, 0.12], vertical_alignment="center")
        with left:
            if st.button("←", key="rev_prev", disabled=index <= 0, help="Previous"):
                set_track(ids[index - 1], index - 1)
                st.rerun()
        with card:
            thumb = track["thumbnail_url"]
            duration = format_duration(track["duration_seconds"], track["duration_text"])
            extras = []
            if track["album"]:
                extras.append(track["album"])
            if duration != "—":
                extras.append(duration)
            extra_line = " · ".join(extras)
            thumb_html = (
                f'<img src="{escape(str(thumb), quote=True)}" '
                'style="width:100%;max-height:220px;object-fit:cover;margin-bottom:1rem;" />'
                if thumb
                else ""
            )
            st.markdown(
                f"""
                <div class="song-card">
                  {thumb_html}
                  <h2>{escape(str(track["title"]))}</h2>
                  <p>{escape(str(track["artists"] or ""))}</p>
                  <p>{escape(extra_line)}</p>
                  <p>{escape("Playlists: " + ", ".join(assigned_names) if assigned_names else "Playlists: none")}</p>
                </div>
                """,
                unsafe_allow_html=True,
            )
        with right:
            if st.button("→", key="rev_next", disabled=index >= len(ids) - 1, help="Next"):
                set_track(ids[index + 1], index + 1)
                st.rerun()

with playlists:
    with st.container(key="review_dests"):
        st.caption("Click to add or remove this song. A song can be in more than one playlist.")
        for dest in destinations:
            is_assigned = dest.name in assigned_names
            row_btn, row_del = st.columns([5, 1], vertical_alignment="center")
            with row_btn:
                if st.button(
                    dest.name.upper() if is_assigned else dest.name,
                    key=f"rev_dest_{dest.id}",
                    type="primary" if is_assigned else "secondary",
                    width="stretch",
                ):
                    ctx.assignments.toggle(int(track["id"]), dest.id)
                    set_track(int(track["id"]), index)
                    st.rerun()
            with row_del:
                if st.button("×", key=f"rev_del_{dest.id}", help=f"Delete playlist {dest.name}", width="stretch"):
                    st.session_state.review_delete_id = dest.id

            if st.session_state.get("review_delete_id") == dest.id:
                confirm, cancel = st.columns(2)
                if confirm.button(f"Delete {dest.name}", key=f"rev_del_yes_{dest.id}"):
                    ctx.assignments.delete_destination(dest.id)
                    st.session_state.review_delete_id = None
                    if scope == dest.id:
                        close_scope()
                    set_track(int(track["id"]), index)
                    st.rerun()
                if cancel.button("Keep", key=f"rev_del_no_{dest.id}"):
                    st.session_state.review_delete_id = None
                    st.rerun()

        if st.button("+ new playlist", width="stretch"):
            st.session_state.review_new_open = True

        if st.session_state.get("review_new_open"):
            new_name = st.text_input("Name", key="review_new_name")
            add_to_song = st.checkbox("Also add this song", value=True)
            if st.button("Create") and new_name.strip():
                dest_id = ctx.assignments.create_destination(new_name)
                if add_to_song:
                    ctx.assignments.assign(int(track["id"]), dest_id)
                st.session_state.review_new_open = False
                set_track(int(track["id"]), index)
                st.rerun()

st.caption(f"{index + 1} of {len(ids)}")
continue_pipeline("review")
