"""Structured, secret-safe logging.

* :class:`RequestContextFilter` adds ``request_id`` (and client IP) to records.
* :class:`RedactingFilter` scrubs secrets from messages and structured args.
* :class:`JSONFormatter` emits one JSON object per line for log pipelines.

Example ``LOGGING`` configuration::

    LOGGING = {
        "version": 1,
        "filters": {
            "context": {"()": "university.core.logging.RequestContextFilter"},
            "redact": {"()": "university.core.logging.RedactingFilter"},
        },
        "formatters": {"json": {"()": "university.core.logging.JSONFormatter"}},
        "handlers": {"console": {"class": "logging.StreamHandler",
                                 "filters": ["context", "redact"],
                                 "formatter": "json"}},
        "root": {"handlers": ["console"], "level": "INFO"},
    }
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Mapping
from typing import Any

from university.core.context import get_request_context

REDACTED = "[REDACTED]"

SENSITIVE_KEYS = frozenset(
    {
        "password",
        "new_password",
        "old_password",
        "current_password",
        "password1",
        "password2",
        "token",
        "access",
        "refresh",
        "access_token",
        "refresh_token",
        "id_token",
        "authorization",
        "cookie",
        "set-cookie",
        "secret",
        "client_secret",
        "api_key",
        "apikey",
        "x-api-key",
        "otp",
        "code",
        "pin",
        "signature",
        "private_key",
        "signing_key",
        "session",
        "sessionid",
        "csrftoken",
        "reset_token",
    }
)

_PATTERNS = [
    (re.compile(r"(?i)(bearer\s+)[A-Za-z0-9\-_\.=]+"), r"\1" + REDACTED),
    (re.compile(r"(?i)(api-key\s+)[A-Za-z0-9\-_\.=]+"), r"\1" + REDACTED),
    (
        re.compile(r"(?i)\b(password|passwd|secret|token|api_key|otp|code)(\"?\s*[:=]\s*\"?)([^\s\"&,;]+)"),
        r"\1\2" + REDACTED,
    ),
    (re.compile(r"\beyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+"), REDACTED),  # JWTs
]


def redact_text(text: str) -> str:
    for pattern, replacement in _PATTERNS:
        text = pattern.sub(replacement, text)
    return text


def redact(value: Any, *, _depth: int = 0) -> Any:
    """Recursively replace values stored under sensitive keys."""
    if _depth > 8:
        return value
    if isinstance(value, Mapping):
        return {
            k: (REDACTED if str(k).lower() in SENSITIVE_KEYS else redact(v, _depth=_depth + 1))
            for k, v in value.items()
        }
    if isinstance(value, (list, tuple)):
        return type(value)(redact(v, _depth=_depth + 1) for v in value)
    if isinstance(value, str):
        return redact_text(value)
    return value


class RedactingFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.msg, str):
            record.msg = redact_text(record.msg)
        if isinstance(record.args, Mapping):
            record.args = redact(record.args)
        elif isinstance(record.args, tuple):
            record.args = tuple(redact(a) for a in record.args)
        return True


class RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        ctx = get_request_context()
        record.request_id = ctx.request_id or "-"
        return True


class JSONFormatter(logging.Formatter):
    RESERVED = frozenset(vars(logging.LogRecord("", 0, "", 0, "", (), None)).keys()) | {"message"}

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", None) or get_request_context().request_id,
        }
        for key, value in record.__dict__.items():
            if key not in self.RESERVED and key not in payload and not key.startswith("_"):
                try:
                    json.dumps(value)
                    payload[key] = redact(value)
                except (TypeError, ValueError):
                    payload[key] = repr(value)
        if record.exc_info:
            payload["exception"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)
