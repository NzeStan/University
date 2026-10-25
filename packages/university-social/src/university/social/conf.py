"""Settings for the social module (``UNIVERSITY["SOCIAL"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

MB = 1024 * 1024

DEFAULTS: dict[str, Any] = {
    "POST_MAX_LENGTH": 5000,
    "COMMENT_MAX_LENGTH": 2000,
    "DEFAULT_VISIBILITY": "public",
    # Visibility levels that restrict a post to an audience scope. Each maps to
    # the scope type of the same name; membership comes from the
    # ``scopes.memberships`` hook (institution, campus, community modules …).
    "SCOPED_VISIBILITIES": ["institution", "campus", "community"],
    "REACTION_TYPES": ["like", "love", "laugh", "wow", "sad", "angry", "support"],
    "MAX_HASHTAGS_PER_POST": 10,
    "MAX_MENTIONS_PER_POST": 20,
    "MAX_LINKS_PER_POST": 5,
    "MAX_MEDIA_PER_POST": 4,
    "MEDIA_MAX_BYTES": 10 * MB,
    "MEDIA_MIME_TYPES": ["image/jpeg", "image/png", "image/gif", "image/webp"],
    # Uploaded media never attached to a post is deleted after this many hours.
    "ORPHAN_MEDIA_HOURS": 24,
    # Minutes after publication during which authors may edit (None = always).
    "EDIT_WINDOW_MINUTES": 24 * 60,
    "LOCATION_ENABLED": False,
    "POLL_MIN_OPTIONS": 2,
    "POLL_MAX_OPTIONS": 4,
    "POLL_MAX_DURATION_DAYS": 14,
    # Feed providers by name (replace any of them with your own class).
    "FEEDS": {
        "home": "university.social.feeds.HomeFeed",
        "explore": "university.social.feeds.ExploreFeed",
        "trending": "university.social.feeds.RankedFeed",
    },
    # Include posts from the viewer's audiences (institution, campus …) at home.
    "HOME_INCLUDES_MEMBER_SCOPES": True,
    "RANKING": {
        "WINDOW_HOURS": 72,
        "CANDIDATES": 500,
        "GRAVITY": 1.5,
        "WEIGHTS": {"reactions": 1.0, "comments": 2.0, "reposts": 3.0},
    },
}

social_settings = ModuleSettings("SOCIAL", DEFAULTS)
