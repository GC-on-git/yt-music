#!/usr/bin/env python3
"""Send 'hi' to the configured LLM to verify LLM_API_KEY."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from src.config import get_settings  # noqa: E402
from src.integrations.llm import LlmClient, LlmError  # noqa: E402


def main() -> int:
    settings = get_settings()
    if not settings.llm_api_key:
        print("LLM_API_KEY is empty. Set it (or OPENAI_API_KEY) in .env.")
        return 1
    print(f"Model: {settings.llm_model}")
    print(f"Base URL: {settings.llm_base_url}")
    try:
        reply = LlmClient(settings).complete_text("hi")
    except LlmError as exc:
        print(f"Failed: {exc}")
        return 1
    print(f"Reply: {reply or '(empty)'}")
    print("LLM key works.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
