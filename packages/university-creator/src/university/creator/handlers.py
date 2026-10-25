"""Feed creator analytics from ids-only platform events.

Only creators (people with a creator profile) are counted, and only as daily
totals. Events from modules that aren't installed simply never arrive.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from university.core.events import Event
from university.creator.constants import Metric
from university.creator.services.analytics import increment, profile_id_for_user


def _count(user_key: str, metric: str, *, skip_self: str | None = None) -> Callable[[Event], None]:
    def handler(event: Event) -> None:
        user_id = event.payload.get(user_key)
        if skip_self and str(event.payload.get(skip_self)) == str(user_id):
            return  # Reacting to or commenting on your own content isn't audience activity.
        profile_id = profile_id_for_user(user_id)
        if profile_id is not None:
            increment(profile_id, metric)

    return handler


def _post_published(event: Event) -> None:
    payload: dict[str, Any] = event.payload
    if payload.get("visibility") in (None, "public", "followers", "community", "institution", "campus"):
        profile_id = profile_id_for_user(payload.get("author_id"))
        if profile_id is not None:
            increment(profile_id, Metric.POSTS_PUBLISHED)


HANDLERS: dict[str, Callable[[Event], None]] = {
    "social.follow.created": _count("followee_id", Metric.FOLLOWERS_GAINED),
    "social.follow.approved": _count("followee_id", Metric.FOLLOWERS_GAINED),
    "social.follow.removed": _count("followee_id", Metric.FOLLOWERS_LOST),
    "social.post.created": _post_published,
    "social.post.reacted": _count("post_author_id", Metric.REACTIONS_RECEIVED, skip_self="user_id"),
    "social.comment.reacted": _count("comment_author_id", Metric.REACTIONS_RECEIVED, skip_self="user_id"),
    "social.comment.created": _count("post_author_id", Metric.COMMENTS_RECEIVED, skip_self="author_id"),
    "social.post.reposted": _count("original_author_id", Metric.REPOSTS_RECEIVED, skip_self="author_id"),
    "social.mention.created": _count("mentioned_user_id", Metric.MENTIONS, skip_self="author_id"),
}


def handle_event(event: Event) -> None:
    handler = HANDLERS.get(event.name)
    if handler is not None:
        handler(event)
