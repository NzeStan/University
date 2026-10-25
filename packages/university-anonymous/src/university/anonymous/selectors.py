"""Read side of anonymous content.

Visibility is audience-based only: published posts in audiences the viewer
belongs to (and public posts if enabled). Blocks deliberately do **not**
apply — hiding a blocked user's anonymous posts would let anyone discover
who wrote them by blocking and watching what disappears.
"""

from __future__ import annotations

from typing import Any

from django.db.models import Exists, OuterRef, Q, QuerySet, Subquery

from university.anonymous.conf import anonymous_settings
from university.anonymous.identity import owns
from university.anonymous.models import (
    AnonymousComment,
    AnonymousPost,
    AnonymousReaction,
    Authorship,
    ContentStatus,
    HiddenPost,
)
from university.core.audiences import member_scopes, member_scopes_by_type
from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid


def _authenticated(user: Any) -> bool:
    return bool(user is not None and getattr(user, "is_authenticated", False))


def audience_q(viewer: Any) -> Q:
    allowed = anonymous_settings.get("ALLOWED_VISIBILITIES", [])
    q = Q(visibility="public") if "public" in allowed else Q(pk__in=[])
    for scope_type, ids in member_scopes_by_type(viewer).items():
        if scope_type in allowed:
            q |= Q(visibility=scope_type, scope_type=scope_type, scope_id__in=ids)
    return q


def visible_posts(viewer: Any) -> QuerySet[AnonymousPost]:
    qs = AnonymousPost.objects.filter(status=ContentStatus.PUBLISHED).filter(audience_q(viewer))
    if _authenticated(viewer):
        qs = qs.exclude(pk__in=HiddenPost.objects.filter(user=viewer).values("post_id"))
    return qs


def authorship(kind: str, object_id: Any) -> Authorship | None:
    return Authorship.objects.filter(kind=kind, object_id=object_id).first()


def is_post_author(viewer: Any, post: AnonymousPost) -> bool:
    record = authorship(Authorship.Kind.POST, post.pk)
    return record is not None and owns(Authorship.Kind.POST, post.pk, viewer, record.owner_token)


def in_audience(viewer: Any, post: AnonymousPost) -> bool:
    allowed = anonymous_settings.get("ALLOWED_VISIBILITIES", [])
    if post.visibility == "public":
        return "public" in allowed
    return post.visibility in allowed and (post.scope_type, post.scope_id) in member_scopes(viewer)


def can_view_post(viewer: Any, post: AnonymousPost) -> bool:
    if post.deleted_at is not None:
        return False
    if is_post_author(viewer, post):
        return True
    return post.status == ContentStatus.PUBLISHED and in_audience(viewer, post)


def get_visible_post(viewer: Any, post_id: Any) -> AnonymousPost:
    post = AnonymousPost.objects.filter(pk=post_id).first() if is_valid_uuid(post_id) else None
    if post is None or not can_view_post(viewer, post):
        raise NotFound("Post not found.")
    return post


def with_viewer_state(qs: QuerySet[AnonymousPost], viewer: Any) -> QuerySet[AnonymousPost]:
    if not _authenticated(viewer):
        return qs
    return qs.annotate(
        viewer_reaction=Subquery(AnonymousReaction.objects.filter(post=OuterRef("pk"), user=viewer).values("kind")[:1]),
        viewer_hidden=Exists(HiddenPost.objects.filter(post=OuterRef("pk"), user=viewer)),
    )


def authored_ids(viewer: Any, kind: str, object_ids: list[Any]) -> set[str]:
    """Which items the viewer wrote — computed per item, never stored."""
    if not _authenticated(viewer) or not object_ids:
        return set()
    return {
        str(row.object_id)
        for row in Authorship.objects.filter(kind=kind, object_id__in=object_ids)
        if owns(kind, row.object_id, viewer, row.owner_token)
    }


def visible_comments(post: AnonymousPost) -> QuerySet[AnonymousComment]:
    return AnonymousComment.objects.filter(post=post, status=ContentStatus.PUBLISHED).order_by("position")
