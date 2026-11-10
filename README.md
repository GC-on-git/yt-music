# YT Music Organizer

Local playlist organizer for YouTube Music.

Import your YouTube Music library. Assign tracks into destination playlists. Publish those playlists back to YouTube.

This project is open source and runs on your machine. You create your own Google Cloud OAuth client. The app does not host accounts or store credentials for other users.

## Requirements

- Python 3.11 or newer
- A Google account
- A Google Cloud project with YouTube Data API v3

## Install

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

## First-time setup

1. Start the app: `streamlit run app.py`
2. Open **Setup**
3. Follow the Google Cloud steps on that page
4. Save your client ID and client secret
5. Sign in with Google

Do not publish the OAuth app in Google Cloud. Keep the consent screen in Testing. Add your Gmail as a test user.

If Google shows `403 access_denied`, that Gmail is not a test user.

Optional CLI path: put the client values in `.env`, then run `python -m src.cli auth`.

Full Google Cloud steps: [docs/setup.md](docs/setup.md).

## Import scope

Import targets YouTube Music content only.

- Skips Watch Later, Liked videos, uploads, and similar YouTube system lists
- Accepts `music.youtube.com` playlist links or raw playlist IDs
- Rejects regular `youtube.com` playlist links
- Skips your own channel uploads

See [docs/pipeline.md](docs/pipeline.md).

## API quota

Library import uses YouTube Data API v3. Google gives most projects **10,000 units per day**. The quota resets at midnight Pacific Time.

Large libraries can hit the limit in one day. If you see `quotaExceeded`, wait for the reset, then run Import again. Already imported playlists are skipped.

`YTMUSIC_FETCH_VIDEO_DETAILS` is `false` by default. Set it to `true` only if you need per-video category filters. That setting uses more quota.

Details: [docs/quota.md](docs/quota.md).

## Optional: Smart Assign

Set `LLM_API_KEY` (or `OPENAI_API_KEY`) in `.env` if you want LLM bulk assign. The rest of the app works without an LLM key.

## Pipeline

| Page | Purpose |
|------|---------|
| Setup | Google OAuth client and sign-in |
| Import | Pull YouTube Music playlists |
| Select playlists | Choose which sources feed Smart Assign |
| Design playlists | Create destination playlists |
| Smart Assign | LLM bulk-assign unassigned tracks |
| Organize playlists | Merge similar playlists. Edit names and descriptions |
| Review | Check and reassign tracks |
| Publish | Create destination playlists on YouTube |

More detail: [docs/pipeline.md](docs/pipeline.md).

## Commands

```bash
streamlit run app.py
python -m src.cli auth
python -m src.cli status
python scripts/ping_llm.py
pytest
```

## Privacy

- `.env`, `data/oauth.json`, and the SQLite database stay on your machine
- Git ignores secrets and local data
- Do not commit client secrets or auth files

## License

MIT. See [LICENSE](LICENSE).
