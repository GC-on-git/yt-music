# Contributing

## Setup

1. Clone the repository.
2. Create a virtual environment.
3. Run `pip install -e ".[dev]"`.
4. Copy `.env.example` to `.env`.
5. Use your own Google OAuth client. Do not commit secrets.

## Tests

```bash
pytest
```

## Scope

Keep changes small and modular.

- Put Google OAuth helpers in `src/services/`
- Put Streamlit pages in `pages/`
- Put shared UI helpers in `src/ui/`
- Put API adapters in `src/integrations/`
- Put YouTube Music import filters in `src/integrations/music_scope.py`

## Docs

Write docs in plain STE-flavored English.

- One instruction per sentence
- Active voice
- No marketing adjectives
- Do not document secrets or personal accounts
- Keep README, `docs/setup.md`, `docs/pipeline.md`, and `docs/quota.md` aligned with behavior

## Do not commit

- `.env`
- `data/oauth.json`
- SQLite databases under `data/`
- API keys
