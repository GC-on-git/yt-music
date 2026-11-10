# Google OAuth setup

Each user creates a Google Cloud OAuth client on their own machine. Do not share the client secret or `data/oauth.json`.

## Steps

1. Open [Google Cloud Console](https://console.cloud.google.com/).
2. Create a project.
3. Enable **YouTube Data API v3**.
4. Open **APIs & Services → OAuth consent screen**.
5. Choose **External**.
6. Keep the app in **Testing**. Do not publish it.
7. Add your Gmail as a test user.
8. Create credentials → **OAuth client ID**.
9. Choose application type **TVs and Limited Input devices**.
10. Copy the client ID and client secret.

## In this app

1. Run `streamlit run app.py`.
2. Open **Setup**.
3. Paste the client ID and client secret.
4. Click **Save client**.
5. Click **Sign in with Google**.
6. Complete the browser sign-in with a test-user Gmail.

The app writes:

- `.env` with `YTMUSIC_CLIENT_ID` and `YTMUSIC_CLIENT_SECRET`
- `data/oauth.json` with the local token file

## CLI alternative

1. Copy `.env.example` to `.env`.
2. Set `YTMUSIC_CLIENT_ID` and `YTMUSIC_CLIENT_SECRET`.
3. Run `python -m src.cli auth`.
4. Run `python -m src.cli status` to confirm the auth file exists.

## Useful `.env` keys

| Key | Purpose |
|-----|---------|
| `YTMUSIC_CLIENT_ID` | Google OAuth client ID |
| `YTMUSIC_CLIENT_SECRET` | Google OAuth client secret |
| `YTMUSIC_AUTH_FILE` | Local token path (default `data/oauth.json`) |
| `YTMUSIC_FETCH_VIDEO_DETAILS` | `false` by default. Set `true` for stricter music filters (uses more quota) |
| `LLM_API_KEY` | Optional. Needed for Smart Assign |

See `.env.example` for the full list.

## Errors

| Message | Action |
|---------|--------|
| `403 access_denied` | Add that Gmail as a test user. Keep Testing. |
| `quotaExceeded` | Wait for the daily reset. See [quota.md](quota.md). |
| Auth file not found | Sign in again from Setup or `python -m src.cli auth`. |
| Missing client ID/secret | Save them on Setup or in `.env`. |

## Notes

- Library import uses YouTube Data API v3 with OAuth.
- Import is scoped to YouTube Music playlists and music tracks. See [pipeline.md](pipeline.md).
- ytmusicapi is unofficial and may break if Google changes APIs.
- Never paste your Google password into this app.
