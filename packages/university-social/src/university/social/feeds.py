"""Feed providers.

Feeds are pluggable (``UNIVERSITY["SOCIAL"]["FEEDS"]``): every provider
starts from :func:`~university.social.selectors.visible_posts` — so blocks,
privacy, audiences, deletion and moderation state are always respected —
and adds its own selection and ordering.

* :class:`HomeFeed` — people you follow, yourself, and your audiences.
* :class:`ExploreFeed` — public posts, newest first.
* :class:`RankedFeed` — recent public posts ranked by engagement velocity
  (not by total likes), with configurable weights and gravity.

Write your own::

    class InstitutionHighlights(FeedProvider):
        requires_auth = True

        def get_queryset(self, viewer, params):
            return visible_posts(viewer).filter(scope_type="institution").order_by("-reaction_count")
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.module_loading import import_string

from university.core.exceptions import NotFound
from university.social.conf import social_settings
from university.social.constants import ContentStatus, Visibility
from university.social.models import Post
from university.social.selectors import audience_q, following_ids, visible_posts, without_muted


class FeedProvider:
    #: Anonymous viewers get 401 when True.
    requires_auth: bool = False
    #: Cursor-paginated querysets (True) or ranked lists with offset paging (False).
    cursor_paginated: bool = True

    def get_queryset(self, viewer: Any, params: Mapping[str, Any]) -> QuerySet[Post]:
        raise NotImplementedError

    def get_items(self, viewer: Any, params: Mapping[str, Any], *, offset: int, limit: int) -> list[Post]:
        """For non-cursor feeds: an ordered page of posts."""
        raise NotImplementedError


class HomeFeed(FeedProvider):
    requires_auth = True

    def get_queryset(self, viewer: Any, params: Mapping[str, Any]) -> QuerySet[Post]:
        selection = Q(author=viewer) | Q(author_id__in=following_ids(viewer))
        if social_settings.get("HOME_INCLUDES_MEMBER_SCOPES", True):
            selection |= audience_q(viewer)
        return without_muted(visible_posts(viewer).filter(selection), viewer)


class ExploreFeed(FeedProvider):
    def get_queryset(self, viewer: Any, params: Mapping[str, Any]) -> QuerySet[Post]:
        return without_muted(visible_posts(viewer).filter(visibility=Visibility.PUBLIC), viewer)


class RankedFeed(FeedProvider):
    """Engagement velocity over a recent window (a "trending" view)."""

    cursor_paginated = False

    def candidates(self, viewer: Any) -> QuerySet[Post]:
        cfg = social_settings.get("RANKING")
        since = timezone.now() - dt.timedelta(hours=int(cfg["WINDOW_HOURS"]))
        qs = visible_posts(viewer).filter(
            visibility=Visibility.PUBLIC, status=ContentStatus.PUBLISHED, created_at__gte=since
        )
        return without_muted(qs, viewer).order_by("-created_at")[: int(cfg["CANDIDATES"])]

    def score(self, post: Post, now: dt.datetime) -> float:
        cfg = social_settings.get("RANKING")
        weights = cfg["WEIGHTS"]
        engagement = (
            weights.get("reactions", 1.0) * post.reaction_count
            + weights.get("comments", 2.0) * post.comment_count
            + weights.get("reposts", 3.0) * post.repost_count
        )
        age_hours = max(0.0, (now - post.created_at).total_seconds() / 3600)
        return (engagement + 1.0) / ((age_hours + 2.0) ** float(cfg["GRAVITY"]))

    def get_items(self, viewer: Any, params: Mapping[str, Any], *, offset: int, limit: int) -> list[Post]:
        from university.core.hooks import Hook, hooks

        now = timezone.now()
        candidates = list(self.candidates(viewer))
        # A trending engine (e.g. university-trending) may supply richer scores (views,
        # velocity, unique actors); fall back to this feed's own formula without one.
        external = hooks.collect(Hook.CONTENT_TRENDING_SCORES, "social.post", [str(p.pk) for p in candidates])
        if external:
            ranked = sorted(candidates, key=lambda p: (external.get(str(p.pk), 0.0), self.score(p, now)), reverse=True)
        else:
            ranked = sorted(candidates, key=lambda p: (self.score(p, now), p.created_at), reverse=True)
        return ranked[offset : offset + limit]


def get_feed(name: str) -> FeedProvider:
    path = (social_settings.get("FEEDS", {}) or {}).get(name)
    if not path:
        raise NotFound("Unknown feed.")
    return import_string(path)()
