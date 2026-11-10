"""OpenAI-compatible chat client for smart playlist assignment."""

from __future__ import annotations

import json
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.config import Settings, get_settings
from src.logging_config import get_logger

logger = get_logger(__name__)


class LlmError(Exception):
    pass


class LlmClient:
    def __init__(self, settings: Settings | None = None, *, complete_fn=None) -> None:
        self.settings = settings or get_settings()
        self._complete_fn = complete_fn

    def is_configured(self) -> bool:
        return bool(self.settings.llm_api_key) or self._complete_fn is not None

    def complete_text(self, user: str, *, system: str | None = None) -> str:
        data = self._chat(
            messages=[
                *([{"role": "system", "content": system}] if system else []),
                {"role": "user", "content": user},
            ]
        )
        return str(((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "").strip()

    def complete_json(self, system: str, user: str) -> Any:
        if self._complete_fn is not None:
            return self._complete_fn(system, user)
        data = self._chat(
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            response_format={"type": "json_object"},
        )
        content = ((data.get("choices") or [{}])[0].get("message") or {}).get("content") or "{}"
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise LlmError("LLM did not return JSON.") from exc

    def _chat(
        self,
        *,
        messages: list[dict[str, str]],
        response_format: dict[str, str] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.llm_api_key:
            raise LlmError("Set LLM_API_KEY (or OPENAI_API_KEY) in .env.")
        payload: dict[str, Any] = {
            "model": self.settings.llm_model,
            "temperature": 0,
            "messages": messages,
        }
        if response_format is not None:
            payload["response_format"] = response_format
        request = Request(
            f"{self.settings.llm_base_url}/chat/completions",
            data=json.dumps(payload).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {self.settings.llm_api_key}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=120) as response:
                return json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace") if exc.fp else ""
            raise LlmError(f"LLM HTTP {exc.code}: {detail or exc.reason}") from exc
        except URLError as exc:
            raise LlmError(f"LLM network error: {exc.reason}") from exc
