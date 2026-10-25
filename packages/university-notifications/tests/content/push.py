"""A push provider that records messages, for tests."""

from __future__ import annotations

from typing import Any

from university.notifications.push import PushMessage, PushResult

SENT: list[PushMessage] = []
#: "ok", "invalid" (every token unregistered) or "error" (raise).
BEHAVIOUR: dict[str, Any] = {"mode": "ok"}


class RecordingPushProvider:
    def send(self, message: PushMessage) -> PushResult:
        mode = BEHAVIOUR["mode"]
        if mode == "error":
            raise RuntimeError("provider down")
        SENT.append(message)
        if mode == "invalid":
            return PushResult(sent=0, invalid_tokens=list(message.tokens))
        return PushResult(sent=len(message.tokens))
