"""Settings for the search module (``UNIVERSITY["SEARCH"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # What gets indexed: content type -> events that (re)index it, events that remove it,
    # and the payload key holding the item id. Items are read through Core content adapters.
    "SOURCES": {
        "social.post": {
            "index": ["social.post.created", "social.post.updated", "social.post.restored"],
            "remove": ["social.post.deleted", "social.post.hidden"],
            "id_key": "post_id",
        },
        "social.comment": {
            "index": ["social.comment.created"],
            "remove": ["social.comment.deleted", "social.comment.hidden"],
            "id_key": "comment_id",
        },
        "anonymous.post": {
            "index": ["anonymous.post.created"],
            "remove": ["anonymous.post.deleted"],
            "id_key": "post_id",
        },
        "community.community": {
            "index": ["community.created", "community.updated"],
            "remove": ["community.archived"],
            "id_key": "community_id",
        },
        "events.event": {
            "index": ["events.event.published", "events.event.updated", "events.event.rescheduled"],
            "remove": ["events.event.hidden", "events.event.cancelled"],
            "id_key": "event_id",
        },
        "marketplace.listing": {
            "index": ["marketplace.listing.published"],
            "remove": ["marketplace.listing.hidden"],
            "id_key": "listing_id",
        },
        "podcast.episode": {"index": ["podcast.episode.published"], "remove": [], "id_key": "episode_id"},
        "creator.campaign": {
            "index": ["creator.campaign.published"],
            "remove": [
                "creator.campaign.closed",
                "creator.campaign.completed",
                "creator.campaign.cancelled",
                "creator.campaign.hidden",
            ],
            "id_key": "campaign_id",
        },
    },
    # Backend: a dotted path, or None to use Core's PROVIDERS.SEARCH (falling back to the
    # database backend when that is the no-op default).
    "BACKEND": None,
    "BACKEND_OPTIONS": {},
    "MIN_QUERY_LENGTH": 2,
    "MAX_QUERY_LENGTH": 100,
    "MAX_RESULTS": 50,
    # People search (handle / display name only — never email or phone).
    "PEOPLE_MIN_QUERY_LENGTH": 3,
    "PEOPLE_MAX_RESULTS": 20,
    # Index from events on the task backend (recommended in production).
    "ASYNC_INDEXING": True,
}

search_settings = ModuleSettings("SEARCH", DEFAULTS)
