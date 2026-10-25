"""Automatic transcription — an AI operation behind a provider protocol.

Configure ``PODCAST.TRANSCRIPTION_PROVIDER`` with a dotted path to a class
implementing :class:`TranscriptionProvider` (for example a wrapper around a
self-hosted Whisper service or a cloud speech-to-text API). Transcription runs
on the task backend; the provider receives a short-lived signed URL to the
episode's audio, never the file system.
"""

from __future__ import annotations

from typing import Any, Protocol


class TranscriptionProvider(Protocol):
    def transcribe(self, *, audio_url: str, language: str) -> list[dict[str, Any]]:
        """Return cues ``[{"start": float, "end": float, "text": str}]``."""


def get_transcription_provider() -> TranscriptionProvider | None:
    from django.utils.module_loading import import_string

    from university.podcast.conf import podcast_settings

    conf = podcast_settings.get("TRANSCRIPTION_PROVIDER")
    if not conf:
        return None
    if isinstance(conf, str):
        return import_string(conf)()
    return import_string(conf["class"])(**(conf.get("options") or {}))
