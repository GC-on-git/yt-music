"""First-run Google OAuth setup for local open-source use."""

from __future__ import annotations

import streamlit as st

from src.app_context import get_context, reset_context
from src.config import PROJECT_ROOT, get_settings
from src.services.env_file import read_env_file
from src.services.oauth_setup_service import (
    auth_status,
    run_device_oauth,
    save_oauth_client,
)
from src.ui.common import page_header

page_header("Setup")
st.caption(
    "Each user creates a Google Cloud OAuth client and signs in on this machine. "
    "Do not share your client secret or oauth.json."
)

settings = get_settings()
status = auth_status(settings)
env_values = read_env_file(PROJECT_ROOT / ".env")

st.subheader("1. Google Cloud client")
st.markdown(
    """
1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project.
3. Enable **YouTube Data API v3**.
4. Open **OAuth consent screen**. Choose External. Keep **Testing**.
5. Add your Gmail as a test user.
6. Create an OAuth client of type **TVs and Limited Input devices**.
7. Copy the client ID and client secret into the fields below.
"""
)

client_id = st.text_input(
    "Client ID",
    value=settings.client_id or env_values.get("YTMUSIC_CLIENT_ID", ""),
)
client_secret = st.text_input(
    "Client secret",
    value=settings.client_secret or env_values.get("YTMUSIC_CLIENT_SECRET", ""),
    type="password",
)

if st.button("Save client", type="primary"):
    try:
        path = save_oauth_client(client_id=client_id, client_secret=client_secret)
        reset_context()
        st.success(f"Saved client settings. Auth file path: {path}")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

st.subheader("2. Sign in with Google")
st.write(status.message)
st.caption(f"Auth file: `{status.auth_file}`")

can_sign_in = bool(client_id.strip() and client_secret.strip())
if st.button("Sign in with Google", disabled=not can_sign_in):
    try:
        auth_file = save_oauth_client(client_id=client_id, client_secret=client_secret)
        with st.spinner("Complete the Google sign-in in your browser…"):
            run_device_oauth(
                client_id=client_id,
                client_secret=client_secret,
                auth_file=auth_file,
                open_browser=True,
            )
        reset_context()
        st.success("Signed in. Import is ready.")
        st.rerun()
    except Exception as exc:  # noqa: BLE001
        st.error(str(exc))

st.subheader("Status")
c1, c2, c3 = st.columns(3)
c1.metric("Client ID", "Yes" if status.client_id_set else "No")
c2.metric("Client secret", "Yes" if status.client_secret_set else "No")
c3.metric("Auth file", "Yes" if status.auth_file_exists else "No")

ctx = get_context()
if ctx.client.is_authenticated():
    st.success("YouTube API access works for this account.")
else:
    st.warning(ctx.client.auth_status_message())

st.subheader("Optional: Smart Assign LLM")
st.caption("Add LLM_API_KEY to `.env` if you want Smart Assign. The app works without it.")
