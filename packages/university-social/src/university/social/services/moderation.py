"""Content moderation actions available within the social module.

Moderators hold ``social.content.moderate`` — platform-wide, or at the
audience scope of the content (e.g. an institution's moderators for posts
restricted to that institution). Every action is audited. Case management,
reports and appeals live in the dedicated moderation module.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound
from university.permissions.scopes import Scope
from university.permissions.services import authorize
from university.social import events
from university.social.constants import ContentStatus
from university.social.models import Comment, Post
from university.social.services.posts import publish_post_side_effects


def _scope(post: Post) -> Scope | None:
    return Scope(post.scope_type, post.scope_id) if post.scope_type else None


def _audit(action: str, actor: Any, obj: Any, post: Post, reason: str) -> None:
    audit(
        action,
        actor=actor,
        target=obj,
        category="moderation",
        scope=(post.scope_type, post.scope_id) if post.scope_type else None,
        metadata={"reason": reason, "author_id": str(obj.author_id)},
    )


def _post(post_id: Any) -> Post:
    post = Post.objects.select_related("author").filter(pk=post_id).first()
    if post is None:
        raise NotFound("Post not found.")
    return post


@transaction.atomic
def hide_post(*, actor: Any, post_id: Any, reason: str) -> Post:
    post = _post(post_id)
    authorize(actor, "social.content.moderate", _scope(post), audit_denial=True)
    if post.status == ContentStatus.HIDDEN:
        raise Conflict("This post is already hidden.", code="already_hidden")
    post.status = ContentStatus.HIDDEN
    post.moderation_reason = reason[:255]
    post.save(update_fields=["status", "moderation_reason", "updated_at"])
    _audit("social.post.hidden", actor, post, post, reason)
    publish(events.POST_HIDDEN, {"post_id": post.pk, "author_id": post.author_id}, actor=actor)
    return post


@transaction.atomic
def restore_post(*, actor: Any, post_id: Any, reason: str = "") -> Post:
    """Publish a hidden post, or approve one held for review."""
    post = _post(post_id)
    authorize(actor, "social.content.moderate", _scope(post), audit_denial=True)
    if post.status == ContentStatus.PUBLISHED:
        raise Conflict("This post is already published.", code="already_published")
    was_pending = post.status == ContentStatus.PENDING_REVIEW
    post.status = ContentStatus.PUBLISHED
    post.moderation_reason = ""
    post.save(update_fields=["status", "moderation_reason", "updated_at"])
    _audit("social.post.restored", actor, post, post, reason)
    if was_pending:
        publish_post_side_effects(post)
    else:
        publish(events.POST_RESTORED, {"post_id": post.pk, "author_id": post.author_id}, actor=actor)
    return post


def _comment(comment_id: Any) -> Comment:
    comment = Comment.objects.select_related("post").filter(pk=comment_id).first()
    if comment is None:
        raise NotFound("Comment not found.")
    return comment


@transaction.atomic
def hide_comment(*, actor: Any, comment_id: Any, reason: str) -> Comment:
    comment = _comment(comment_id)
    authorize(actor, "social.content.moderate", _scope(comment.post), audit_denial=True)
    comment.status = ContentStatus.HIDDEN
    comment.moderation_reason = reason[:255]
    comment.save(update_fields=["status", "moderation_reason", "updated_at"])
    _audit("social.comment.hidden", actor, comment, comment.post, reason)
    publish(events.COMMENT_HIDDEN, {"comment_id": comment.pk, "author_id": comment.author_id}, actor=actor)
    return comment


@transaction.atomic
def restore_comment(*, actor: Any, comment_id: Any, reason: str = "") -> Comment:
    comment = _comment(comment_id)
    authorize(actor, "social.content.moderate", _scope(comment.post), audit_denial=True)
    comment.status = ContentStatus.PUBLISHED
    comment.moderation_reason = ""
    comment.save(update_fields=["status", "moderation_reason", "updated_at"])
    _audit("social.comment.restored", actor, comment, comment.post, reason)
    return comment
