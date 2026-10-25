"""Comments and replies (threads flattened to two levels)."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.audiences import ensure_can_post_to
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import NotFound, PermissionDenied, ValidationError
from university.core.ratelimit import rate_limit
from university.social import events
from university.social.conf import social_settings
from university.social.constants import ContentStatus
from university.social.models import Comment, Post
from university.social.selectors import can_view_post, get_visible_post, is_blocked, is_moderator
from university.social.services.common import check_length, ensure_can_interact, increment, screen_content
from university.social.services.tagging import sync_comment_mentions


def _payload(comment: Comment, post: Post) -> dict[str, Any]:
    return {
        "comment_id": comment.pk,
        "post_id": post.pk,
        "author_id": comment.author_id,
        "post_author_id": post.author_id,
        "parent_id": comment.parent_id,
    }


@transaction.atomic
def create_comment(*, author: Any, post_id: Any, body: str, parent_id: Any = None) -> Comment:
    rate_limit("social_comment", key=str(author.pk))
    ensure_can_create(author, "social.comment")
    post = get_visible_post(author, post_id)
    if post.status != ContentStatus.PUBLISHED or not post.comments_enabled:
        raise PermissionDenied("Comments are turned off for this post.", code="comments_disabled")
    ensure_can_interact(author, post.author, "comment")
    if post.scope_type:
        ensure_can_post_to(author, post.scope_type, post.scope_id, "social.comment")
    body = check_length(body, int(social_settings.get("COMMENT_MAX_LENGTH", 2000)))
    if not body:
        raise ValidationError(details={"body": ["This field may not be blank."]})
    parent = None
    if parent_id:
        parent = Comment.objects.filter(pk=parent_id, post=post, status=ContentStatus.PUBLISHED).first()
        if parent is None or is_blocked(author, parent.author):
            raise ValidationError(details={"parent": ["Comment not found."]})
        if parent.parent_id:
            parent = Comment.objects.get(pk=parent.parent_id)  # flatten to two levels
    status = screen_content(body, actor=author, kind="comment")
    comment = Comment.objects.create(post=post, author=author, parent=parent, body=body, status=status)
    increment(Post, post.pk, "comment_count", +1)
    if parent is not None:
        increment(Comment, parent.pk, "reply_count", +1)
    published = status == ContentStatus.PUBLISHED
    sync_comment_mentions(comment, notify=published)
    if published:
        publish(events.COMMENT_CREATED, _payload(comment, post), actor=author)
    return comment


def _load(comment_id: Any) -> Comment:
    comment = Comment.objects.select_related("post", "post__author", "author").filter(pk=comment_id).first()
    if comment is None:
        raise NotFound("Comment not found.")
    return comment


@transaction.atomic
def edit_comment(*, actor: Any, comment_id: Any, body: str) -> Comment:
    comment = _load(comment_id)
    if comment.author_id != actor.pk:
        if not can_view_post(actor, comment.post):
            raise NotFound("Comment not found.")
        raise PermissionDenied("You can only edit your own comments.")
    window = social_settings.get("EDIT_WINDOW_MINUTES")
    if window is not None and comment.created_at < timezone.now() - dt.timedelta(minutes=int(window)):
        raise ValidationError("The edit window for this comment has passed.", code="edit_window_closed")
    body = check_length(body, int(social_settings.get("COMMENT_MAX_LENGTH", 2000)))
    if not body:
        raise ValidationError(details={"body": ["This field may not be blank."]})
    status = screen_content(body, actor=actor, kind="comment")
    comment.body = body
    comment.edited_at = timezone.now()
    if status == ContentStatus.PENDING_REVIEW:
        comment.status = status
    comment.save(update_fields=["body", "edited_at", "status", "updated_at"])
    sync_comment_mentions(comment, notify=comment.status == ContentStatus.PUBLISHED)
    return comment


def remove_comment_records(comment: Comment) -> None:
    """Soft-delete a comment and fix counters (no authorisation)."""
    comment.delete()
    increment(Post, comment.post_id, "comment_count", -1)
    if comment.parent_id:
        increment(Comment, comment.parent_id, "reply_count", -1)


@transaction.atomic
def delete_comment(*, actor: Any, comment_id: Any, reason: str = "") -> None:
    """Authors, the post's author, and moderators may delete a comment."""
    comment = _load(comment_id)
    post = comment.post
    is_author = comment.author_id == actor.pk
    is_post_owner = post.author_id == actor.pk
    moderator = is_moderator(actor, post)
    if not (is_author or is_post_owner or moderator):
        if not can_view_post(actor, post):
            raise NotFound("Comment not found.")
        raise PermissionDenied("You can't delete this comment.")
    remove_comment_records(comment)
    if not (is_author or is_post_owner):
        audit(
            "social.comment.removed",
            actor=actor,
            target=comment,
            category="moderation",
            scope=(post.scope_type, post.scope_id) if post.scope_type else None,
            metadata={"reason": reason, "author_id": str(comment.author_id)},
        )
    publish(events.COMMENT_DELETED, _payload(comment, post), actor=actor)
