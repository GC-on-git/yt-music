#!/usr/bin/env bash
# Create a local venv and install the project (with dev extras).
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

python -m pip install --upgrade pip
pip install -e ".[dev]"

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — fill in OAuth credentials if needed."
else
  echo ".env already present."
fi

echo
echo "Next:"
echo "  source .venv/bin/activate"
echo "  python -m src.cli auth"
echo "  streamlit run app.py"
echo "  pytest"
