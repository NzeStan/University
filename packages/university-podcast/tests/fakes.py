"""A transcription provider for tests."""

from __future__ import annotations

from typing import Any

CALLS: list[dict[str, Any]] = []


class FakeTranscriber:
    def transcribe(self, *, audio_url: str, language: str) -> list[dict[str, Any]]:
        CALLS.append({"audio_url": audio_url, "language": language})
        return [{"start": 0, "end": 1.5, "text": "Welcome to the show."}, {"start": 1.5, "end": 3, "text": "  "}]
