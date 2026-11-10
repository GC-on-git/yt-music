"""Streamlit session-state helpers for the Review page.

Encapsulates the three session keys (``review_scope``, ``review_track_id``,
``review_index``) that together form the Review UI state machine:

* **scope = None**  →  playlist picker (root)
* **scope = "unassigned" | dest.id**  →  track carousel inside that scope
* **review_delete_id / review_new_open**  →  transient modal sub-states

This module owns reads and writes to those keys so the page file never
manipulates ``st.session_state`` directly for navigation.
"""

from __future__ import annotations

import streamlit as st

SCOPE_UNASSIGNED = "unassigned"

_KEY_SCOPE = "review_scope"
_KEY_TRACK_ID = "review_track_id"
_KEY_INDEX = "review_index"


def get_scope() -> str | int | None:
    return st.session_state.get(_KEY_SCOPE)


def open_scope(scope: str | int) -> None:
    st.session_state[_KEY_SCOPE] = scope
    st.session_state[_KEY_TRACK_ID] = None
    st.session_state[_KEY_INDEX] = 0
    st.rerun()


def close_scope() -> None:
    st.session_state[_KEY_SCOPE] = None
    st.session_state[_KEY_TRACK_ID] = None
    st.session_state[_KEY_INDEX] = 0
    st.rerun()


def ensure_track_index(ids: list[int]) -> tuple[int, int]:
    """Return ``(track_id, index)`` clamped to the current id list.

    Handles stale ``review_track_id`` after deletes/merges by falling back to
    the nearest valid index.
    """
    current_id = st.session_state.get(_KEY_TRACK_ID)
    prev_index = int(st.session_state.get(_KEY_INDEX) or 0)
    if current_id not in ids:
        current_id = ids[min(prev_index, len(ids) - 1)]
    index = ids.index(current_id)
    st.session_state[_KEY_TRACK_ID] = current_id
    st.session_state[_KEY_INDEX] = index
    return current_id, index


def set_track(track_id: int, index: int) -> None:
    st.session_state[_KEY_TRACK_ID] = track_id
    st.session_state[_KEY_INDEX] = index
