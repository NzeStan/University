"""Settings for the trending module (``UNIVERSITY["TRENDING"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Event -> signal. "content_type" (or "content_type_key" to read it from the payload),
    # "id_key" (payload key of the item's id) and "signal" (a key of WEIGHTS).
    "SIGNALS": {
        "content.viewed": {"content_type_key": "content_type", "id_key": "object_id", "signal": "view"},
        "social.post.reacted": {"content_type": "social.post", "id_key": "post_id", "signal": "reaction"},
        "social.comment.created": {"content_type": "social.post", "id_key": "post_id", "signal": "comment"},
        "social.post.reposted": {"content_type": "social.post", "id_key": "original_post_id", "signal": "share"},
        "anonymous.comment.created": {"content_type": "anonymous.post", "id_key": "post_id", "signal": "comment"},
        "events.registration.confirmed": {
            "content_type": "events.event",
            "id_key": "event_id",
            "signal": "registration",
        },
        "community.member.joined": {"content_type": "community.community", "id_key": "community_id", "signal": "join"},
        "marketplace.order.created": {"content_type": "marketplace.listing", "id_key": "listing_id", "signal": "order"},
    },
    "WEIGHTS": {
        "view": 0.2,
        "reaction": 1.0,
        "comment": 3.0,
        "share": 5.0,
        "registration": 4.0,
        "join": 3.0,
        "order": 4.0,
    },
    # Signals older than this don't count.
    "WINDOW_HOURS": 48,
    # Velocity compares this recent period with the rest of the window.
    "VELOCITY_HOURS": 6,
    "VELOCITY_WEIGHT": 1.0,
    # Recency decay: score / (age_hours + 2) ** GRAVITY.
    "GRAVITY": 1.5,
    # Items need engagement from at least this many different people (stops one account pumping an item).
    "MIN_UNIQUE_ACTORS": 2,
    # The same person's repeated signal on the same item counts once per this window.
    "DEDUPE_HOURS": 24,
    # At most this many items from one author in a trending list (diversity).
    "MAX_PER_AUTHOR": 2,
    "MAX_ITEMS_PER_TYPE": 500,
    # Swap the formula entirely (a class with ``score(stats) -> float``).
    "ALGORITHM": "university.trending.algorithms.GravityVelocity",
    "SIGNAL_RETENTION_HOURS": 168,
}

trending_settings = ModuleSettings("TRENDING", DEFAULTS)
