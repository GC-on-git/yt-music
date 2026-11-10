"""Export and backup."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

from src.app_context import get_context
from src.config import PROJECT_ROOT
from src.ui.common import page_header

ctx = get_context()
page_header("Export")

export_dir = PROJECT_ROOT / "data" / "exports"
c1, c2 = st.columns(2)
if c1.button("CSV"):
    ctx.exports.write_csv(export_dir / "organization_plan.csv")
    st.download_button("Download CSV", ctx.exports.to_csv(), file_name="organization_plan.csv")
if c2.button("JSON"):
    ctx.exports.write_json(export_dir / "organization_plan.json")
    st.download_button("Download JSON", ctx.exports.to_json(), file_name="organization_plan.json")

st.subheader("Backup")
if st.button("Backup"):
    try:
        path = ctx.backups.backup()
        st.success(str(path))
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

backups = ctx.backups.list_backups()
if backups:
    choice = st.selectbox("Restore", [str(p) for p in backups])
    if st.button("Restore"):
        ctx.backups.restore(Path(choice))
        st.rerun()
