"""Central visual theme injection. Presentation only."""

from __future__ import annotations

from pathlib import Path

import streamlit as st

_CSS_PATH = Path(__file__).with_name("theme.css")
_CSS = _CSS_PATH.read_text(encoding="utf-8")


def apply_theme() -> None:
    st.html(f"<style>{_CSS}</style>")
