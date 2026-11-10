"""Shared Streamlit UI helpers."""

from __future__ import annotations

import pandas as pd
import streamlit as st

from src.app_context import get_context
from src.models.state_machines import pipeline_readiness
from src.services.assignment_service import labeled_track_map
from src.ui.source_playlists import (
    IMPORTED_WINDOWS,
    PRIVACY_OPTIONS,
    filter_source_playlists,
    normalize_privacy,
    parse_playlist_time,
)
from src.ui.theme import apply_theme

PIPELINE: tuple[tuple[str, str, str], ...] = (
    ("import", "Import", "pages/1_Import.py"),
    ("select", "Select playlists", "pages/2_Select_Playlists.py"),
    ("design", "Design playlists", "pages/3_Playlists.py"),
    ("smart", "Smart Assign", "pages/4_Smart_Assign.py"),
    ("organize", "Organize playlists", "pages/5_Organize_Playlists.py"),
    ("review", "Review", "pages/5_Review.py"),
    ("publish", "Publish", "pages/7_Publish.py"),
)


def page_header(title: str, *, step: str | None = None) -> None:
    apply_theme()
    st.title(title)
    if step:
        show_pipeline(step)


def show_auth_banner() -> None:
    ctx = get_context()
    if ctx.client.is_authenticated():
        return
    st.warning(ctx.client.auth_status_message())
    if st.button("Open Setup", key="open_setup_banner"):
        st.switch_page("pages/0_Setup.py")


def show_pipeline(current: str) -> None:
    labels = [label for _, label, _ in PIPELINE]
    current_label = next(label for key, label, _ in PIPELINE if key == current)
    picked = st.segmented_control(
        "Step",
        labels,
        default=current_label,
        key=f"pipeline_step_{current}",
        required=True,
        width="stretch",
        wrap=True,
        label_visibility="collapsed",
    )
    if picked and picked != current_label:
        dest = next(path for _, label, path in PIPELINE if label == picked)
        st.switch_page(dest)


def continue_pipeline(current: str, *, disabled: bool = False) -> None:
    nxt = _next_step(current)
    if nxt is None:
        return
    next_key, label, path = nxt
    if not disabled:
        ctx = get_context()
        ready, reason = pipeline_readiness(ctx.repo, next_key)
        if not ready:
            disabled = True
    else:
        reason = None
    if st.button(f"Continue to {label}", type="primary", disabled=disabled):
        st.switch_page(path)
    if disabled and reason:
        st.caption(reason)


def source_playlist_picker(*, key_prefix: str) -> int:
    """Filterable playlist table. Returns how many playlists are selected."""
    ctx = get_context()
    rows = ctx.repo.list_source_playlists()
    if not rows:
        return 0

    privacy_choices = list(PRIVACY_OPTIONS)
    if any(normalize_privacy(row["privacy"]) == "Unknown" for row in rows):
        privacy_choices.append("Unknown")

    search_c, privacy_c, imported_c = st.columns([1.4, 1.1, 1.3])
    with search_c:
        search = st.text_input("Search", key=f"{key_prefix}_search")
    with privacy_c:
        privacies = st.pills(
            "Privacy",
            privacy_choices,
            selection_mode="multi",
            wrap=True,
            key=f"{key_prefix}_privacy",
        )
    with imported_c:
        imported = st.segmented_control(
            "Last imported",
            list(IMPORTED_WINDOWS),
            default=IMPORTED_WINDOWS[0],
            key=f"{key_prefix}_imported",
        ) or IMPORTED_WINDOWS[0]

    visible = filter_source_playlists(
        rows,
        search=search or "",
        privacies=privacies,
        imported=imported,
    )
    visible_ids = [int(row["id"]) for row in visible]
    stored_selected = {int(row["id"]) for row in visible if row["include_in_smart_assign"]}

    nonce_key = f"{key_prefix}_table_nonce"
    all_c, none_c = st.columns(2)
    if all_c.button("Select all", key=f"{key_prefix}_all", disabled=not visible_ids):
        ctx.repo.set_source_playlists_smart_assign(visible_ids, True)
        ctx.assignments.sync_predesigned_from_excluded_sources()
        st.session_state[nonce_key] = int(st.session_state.get(nonce_key) or 0) + 1
        st.rerun()
    if none_c.button("Select none", key=f"{key_prefix}_none", disabled=not visible_ids):
        ctx.repo.set_source_playlists_smart_assign(visible_ids, False)
        ctx.assignments.sync_predesigned_from_excluded_sources()
        st.session_state[nonce_key] = int(st.session_state.get(nonce_key) or 0) + 1
        st.rerun()

    if not visible:
        st.caption(f"0 shown · {sum(1 for row in rows if row['include_in_smart_assign'])} selected for Smart Assign")
        st.info("No playlists match these filters.")
        return sum(1 for row in rows if row["include_in_smart_assign"])

    table = pd.DataFrame(
        [
            {
                "playlist": row["title"],
                "tracks": int(row["local_track_count"] or 0),
                "privacy": normalize_privacy(row["privacy"]),
                "last_imported": parse_playlist_time(row["last_import_at"]),
                "status": str(row["import_status"] or "").replace("_", " "),
            }
            for row in visible
        ]
    )
    default_rows = [index for index, row in enumerate(visible) if row["include_in_smart_assign"]]
    privacy_key = ",".join(privacies) if privacies else ""
    event = st.dataframe(
        table,
        width="stretch",
        hide_index=True,
        on_select="rerun",
        selection_mode="multi-row",
        selection_default={"selection": {"rows": default_rows}},
        placeholder="",
        alt="Imported playlists you can include in Smart Assign",
        column_config={
            "playlist": st.column_config.TextColumn("Playlist", pinned=True),
            "tracks": st.column_config.NumberColumn("Tracks"),
            "privacy": st.column_config.TextColumn("Privacy"),
            "last_imported": st.column_config.DatetimeColumn("Last imported", format="MMM D, YYYY"),
            "status": st.column_config.TextColumn("Status"),
        },
        key=f"{key_prefix}_table_{search}_{privacy_key}_{imported}_{st.session_state.get(nonce_key, 0)}",
    )
    chosen_ids = {visible_ids[index] for index in event.selection.rows if 0 <= index < len(visible_ids)}
    to_enable = chosen_ids - stored_selected
    to_disable = stored_selected - chosen_ids
    if to_enable:
        ctx.repo.set_source_playlists_smart_assign(to_enable, True)
    if to_disable:
        ctx.repo.set_source_playlists_smart_assign(to_disable, False)
    if to_enable or to_disable:
        sync = ctx.assignments.sync_predesigned_from_excluded_sources()
        excluded = int(sync["excluded"])
        if excluded:
            st.caption(
                f"Excluded playlists are treated as pre-designed destinations "
                f"({sync['created']} created, {sync['assigned']} track links)."
            )
    selected_total = sum(1 for row in rows if row["include_in_smart_assign"]) + len(to_enable) - len(to_disable)
    excluded_total = len(rows) - selected_total
    st.caption(
        f"{len(visible)} shown · {selected_total} selected for Smart Assign · "
        f"{excluded_total} excluded become pre-designed playlists"
    )
    return selected_total


def format_duration(seconds: int | None, text: str | None = None) -> str:
    if text:
        return text
    if seconds is None:
        return "—"
    m, s = divmod(int(seconds), 60)
    h, m = divmod(m, 60)
    if h:
        return f"{h}:{m:02d}:{s:02d}"
    return f"{m}:{s:02d}"


def track_select_options(search: str | None = None) -> dict[str, int]:
    ctx = get_context()
    rows = ctx.repo.assignable_tracks(search=search or None)
    return labeled_track_map(rows)


def _next_step(current: str) -> tuple[str, str, str] | None:
    keys = [key for key, _, _ in PIPELINE]
    try:
        index = keys.index(current)
    except ValueError:
        return None
    if index + 1 >= len(PIPELINE):
        return None
    return PIPELINE[index + 1]
