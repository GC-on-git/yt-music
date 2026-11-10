"""Standard logging setup. Never log auth material."""

from __future__ import annotations

import logging
import re
from typing import Any

_SENSITIVE_KEYS = re.compile(
    r"(cookie|authorization|token|secret|password|oauth|client_secret|refresh_token)",
    re.IGNORECASE,
)


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        if _SENSITIVE_KEYS.search(msg):
            record.msg = "[REDACTED: possible credentials in log message]"
            record.args = ()
        return True


def configure_logging(level: str = "INFO") -> None:
    root = logging.getLogger()
    if getattr(root, "_ytm_organizer_configured", False):
        root.setLevel(level)
        return

    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    handler.addFilter(RedactingFilter())
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)
    setattr(root, "_ytm_organizer_configured", True)


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)


def safe_error_message(exc: BaseException) -> str:
    """Return an error string with obvious credential-looking fragments removed."""
    text = str(exc)
    if _SENSITIVE_KEYS.search(text):
        return f"{type(exc).__name__}: [details redacted]"
    return f"{type(exc).__name__}: {text}"


def redact_mapping(data: dict[str, Any]) -> dict[str, Any]:
    return {
        k: ("***" if _SENSITIVE_KEYS.search(k) else v)
        for k, v in data.items()
    }
