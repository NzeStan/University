"""Settings for the podcast module (``UNIVERSITY["PODCAST"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    "CATEGORIES": [
        "Arts",
        "Business",
        "Comedy",
        "Education",
        "Fiction",
        "Health & Fitness",
        "History",
        "Leisure",
        "Music",
        "News",
        "Religion & Spirituality",
        "Science",
        "Society & Culture",
        "Sports",
        "Technology",
        "True Crime",
        "TV & Film",
    ],
    "LANGUAGES": ["en", "fr", "pt", "ar", "sw", "ha", "yo", "ig", "am", "zu", "pcm"],
    # "verified_users" or "permission" (podcast.create). Hosting for a scope needs podcast.manage there.
    "CREATION_POLICY": "verified_users",
    "MAX_PODCASTS_PER_USER": 5,
    "MAX_MEMBERS": 10,
    "MAX_GUESTS_PER_EPISODE": 10,
    # Absolute base for links in RSS feeds (enclosures, covers), e.g. "https://api.example.edu".
    "PUBLIC_API_URL": "http://localhost:8000",
    "SHOW_URL": "http://localhost:3000/podcasts/{slug}",
    "TRANSCRIPT_MAX_BYTES": 2 * 1024 * 1024,
    # Automatic transcription (an AI operation). None disables it; see university.podcast.transcription.
    "TRANSCRIPTION_PROVIDER": None,
    # A play counts as completed past this share of the duration.
    "COMPLETION_THRESHOLD": 0.9,
    "PLAY_DEDUPE_HOURS": 24,
    "STATS_RETENTION_DAYS": 730,
}

podcast_settings = ModuleSettings("PODCAST", DEFAULTS)
