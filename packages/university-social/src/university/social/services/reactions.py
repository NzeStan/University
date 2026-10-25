"""Reactions and bookmarks. All operations are idempotent and race-safe."""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from university.core.events import publish
from university.core.exceptions import NotFound, ValidationError
from university.core.ratelimit import rate_limit
from university.social import events
from university.social.conf import social_settings
from university.social.constants import ContentStatus
from university.social.models import Bookmark, Comment, CommentReaction, Post, PostReaction
from university.social.selectors import get_visible_post, is_blocked
from university.social.services.common import increment


def _validate_kind(kind: str) -> str:
    if kind not in social_settings.get("REACTION_TYPES", []):
        raise ValidationError(details={"kind": ["Unknown reaction."]})
    return kind


def _upsert(model: type, lookup: dict[str, Any], kind: str) -> tuple[Any, bool]:
    existing = model.objects.filter(**lookup).first()
    if existing is not None:
        if existing.kind != kind:
            model.objects.filter(pk=existing.pk).update(kind=kind)
            existing.kind = kind
        return existing, False
    try:
        with transaction.atomic():
            return model.objects.create(kind=kind, **lookup), True
    except IntegrityError:  # a concurrent request won
        model.objects.filter(**lookup).update(kind=kind)
        return model.objects.get(**lookup), False


@transaction.atomic
def react_to_post(*, user: Any, post_id: Any, kind: str) -> PostReaction:
    rate_limit("social_reaction", key=str(user.pk))
    _validate_kind(kind)
    post = get_visible_post(user, post_id)
    if post.status != ContentStatus.PUBLISHED:
        raise NotFound("Post not found.")
    reaction, created = _upsert(PostReaction, {"post": post, "user": user}, kind)
    if created:
        increment(Post, post.pk, "reaction_count", +1)
        publish(
            events.POST_REACTED,
            {"post_id": post.pk, "post_author_id": post.author_id, "user_id": user.pk, "kind": kind},
            actor=user,
        )
    return reaction


@transaction.atomic
def remove_post_reaction(*, user: Any, post_id: Any) -> None:
    deleted, _ = PostReaction.objects.filter(post_id=post_id, user=user).delete()
    if deleted:
        increment(Post, post_id, "reaction_count", -1)


def _visible_comment(user: Any, comment_id: Any) -> Comment:
    comment = Comment.objects.select_related("author").filter(pk=comment_id, status=ContentStatus.PUBLISHED).first()
    if comment is None or is_blocked(user, comment.author):
        raise NotFound("Comment not found.")
    get_visible_post(user, comment.post_id)
    return comment


@transaction.atomic
def react_to_comment(*, user: Any, comment_id: Any, kind: str) -> CommentReaction:
    rate_limit("social_reaction", key=str(user.pk))
    _validate_kind(kind)
    comment = _visible_comment(user, comment_id)
    reaction, created = _upsert(CommentReaction, {"comment": comment, "user": user}, kind)
    if created:
        increment(Comment, comment.pk, "reaction_count", +1)
        publish(
            events.COMMENT_REACTED,
            {"comment_id": comment.pk, "comment_author_id": comment.author_id, "user_id": user.pk, "kind": kind},
            actor=user,
        )
    return reaction


@transaction.atomic
def remove_comment_reaction(*, user: Any, comment_id: Any) -> None:
    deleted, _ = CommentReaction.objects.filter(comment_id=comment_id, user=user).delete()
    if deleted:
        increment(Comment, comment_id, "reaction_count", -1)


@transaction.atomic
def bookmark_post(*, user: Any, post_id: Any) -> Bookmark:
    post = get_visible_post(user, post_id)
    bookmark, _ = Bookmark.objects.get_or_create(post=post, user=user)
    return bookmark


@transaction.atomic
def remove_bookmark(*, user: Any, post_id: Any) -> None:
    Bookmark.objects.filter(post_id=post_id, user=user).delete()
