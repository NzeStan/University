"""Posts: create, edit (with revision history), delete, repost and quote."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.audiences import ensure_can_post_to, is_member
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.ratelimit import rate_limit
from university.social import events
from university.social.conf import social_settings
from university.social.constants import ContentStatus, Visibility
from university.social.models import Post, PostRevision
from university.social.parsing import extract_links
from university.social.selectors import can_view_post, get_visible_post, is_moderator
from university.social.services.common import check_length, increment, profile_increment, screen_content
from university.social.services.media import claim_media
from university.social.services.polls import create_poll
from university.social.services.profiles import get_social_profile
from university.social.services.tagging import release_hashtags, sync_hashtags, sync_post_mentions


def _post_payload(post: Post) -> dict[str, Any]:
    return {
        "post_id": post.pk,
        "author_id": post.author_id,
        "visibility": post.visibility,
        "scope_type": post.scope_type,
        "scope_id": post.scope_id,
    }


def _resolve_audience(author: Any, visibility: str, scope_id: Any) -> tuple[str, str]:
    scoped = social_settings.get("SCOPED_VISIBILITIES", [])
    if visibility in scoped:
        if not scope_id:
            raise ValidationError(details={"scope_id": ["Required for this visibility."]})
        if not is_member(author, visibility, scope_id):
            raise PermissionDenied("You are not a member of this audience.", code="not_audience_member")
        ensure_can_post_to(author, visibility, scope_id, "social.post")
        return visibility, str(scope_id)
    if scope_id:
        raise ValidationError(details={"scope_id": ["Only allowed for audience visibilities."]})
    return "", ""


def publish_post_side_effects(post: Post) -> None:
    """Side effects of a post becoming visible to others."""
    sync_post_mentions(post, notify=True)
    publish(events.POST_CREATED, _post_payload(post), actor=post.author)


@transaction.atomic
def create_post(
    *,
    author: Any,
    body: str = "",
    visibility: str | None = None,
    scope_id: Any = None,
    media: list[Any] | None = None,
    poll: Mapping[str, Any] | None = None,
    location: str = "",
    comments_enabled: bool = True,
) -> Post:
    rate_limit("social_post", key=str(author.pk))
    ensure_can_create(author, "social.post")
    body = check_length(body, int(social_settings.get("POST_MAX_LENGTH", 5000)))
    visibility = visibility or get_social_profile(author).default_post_visibility
    if visibility not in Visibility.values:
        raise ValidationError(details={"visibility": ["Invalid visibility."]})
    scope_type, scope_id_str = _resolve_audience(author, visibility, scope_id)
    attachments = claim_media(author, media or [])
    if not body and not attachments and not poll:
        raise ValidationError("A post needs text, media or a poll.", code="empty_post")
    if location and not social_settings.get("LOCATION_ENABLED", False):
        raise ValidationError(details={"location": ["Location is not enabled."]})
    status = screen_content(body, actor=author, kind="post")

    post = Post.objects.create(
        author=author,
        body=body,
        visibility=visibility,
        scope_type=scope_type,
        scope_id=scope_id_str,
        status=status,
        links=extract_links(body, limit=int(social_settings.get("MAX_LINKS_PER_POST", 5))),
        location=location.strip()[:100],
        comments_enabled=comments_enabled,
    )
    for position, item in enumerate(attachments):
        item.post = post
        item.position = position
        item.save(update_fields=["post", "position", "updated_at"])
    if poll:
        create_poll(post, poll)
    sync_hashtags(post)
    profile_increment(author.pk, "posts_count", +1)
    if status == ContentStatus.PUBLISHED:
        publish_post_side_effects(post)
    else:
        sync_post_mentions(post, notify=False)
    return post


def _own_post(actor: Any, post_id: Any) -> Post:
    post = get_visible_post(actor, post_id)  # 404 when invisible
    if post.author_id != actor.pk:
        raise PermissionDenied("You can only change your own posts.")
    return post


@transaction.atomic
def edit_post(*, actor: Any, post_id: Any, data: Mapping[str, Any]) -> Post:
    post = _own_post(actor, post_id)
    unknown = set(data) - {"body", "comments_enabled"}
    if unknown:
        raise ValidationError(details={f: ["This field cannot be changed."] for f in sorted(unknown)})
    if "body" in data and data["body"] != post.body:
        if post.is_pure_repost:
            raise ValidationError("Reposts cannot be edited.", code="not_editable")
        window = social_settings.get("EDIT_WINDOW_MINUTES")
        if window is not None and post.created_at < timezone.now() - dt.timedelta(minutes=int(window)):
            raise ValidationError("The edit window for this post has passed.", code="edit_window_closed")
        body = check_length(data["body"], int(social_settings.get("POST_MAX_LENGTH", 5000)))
        if not body and not post.media.exists() and not hasattr(post, "poll"):
            raise ValidationError("A post needs text, media or a poll.", code="empty_post")
        status = screen_content(body, actor=actor, kind="post")
        PostRevision.objects.create(post=post, body=post.body)
        post.body = body
        post.links = extract_links(body, limit=int(social_settings.get("MAX_LINKS_PER_POST", 5)))
        post.edited_at = timezone.now()
        if post.status == ContentStatus.PUBLISHED and status == ContentStatus.PENDING_REVIEW:
            post.status = status
        post.save(update_fields=["body", "links", "edited_at", "status", "updated_at"])
        sync_hashtags(post)
        sync_post_mentions(post, notify=post.status == ContentStatus.PUBLISHED)
    if "comments_enabled" in data:
        post.comments_enabled = bool(data["comments_enabled"])
        post.save(update_fields=["comments_enabled", "updated_at"])
    publish(events.POST_UPDATED, _post_payload(post), actor=actor)
    return post


@transaction.atomic
def delete_post(*, actor: Any, post_id: Any, reason: str = "") -> None:
    post = Post.objects.select_related("author").filter(pk=post_id).first()
    if post is None:
        raise NotFound("Post not found.")
    is_author = post.author_id == actor.pk
    if not is_author:
        if not can_view_post(actor, post) and not is_moderator(actor, post):
            raise NotFound("Post not found.")
        if not is_moderator(actor, post):
            raise PermissionDenied("You can only delete your own posts.")
    remove_post_records(post)
    if not is_author:
        audit(
            "social.post.removed",
            actor=actor,
            target=post,
            category="moderation",
            scope=(post.scope_type, post.scope_id) if post.scope_type else None,
            metadata={"reason": reason, "author_id": str(post.author_id)},
        )
    publish(events.POST_DELETED, _post_payload(post), actor=actor)


def remove_post_records(post: Post) -> None:
    """Soft-delete a post and fix the counters it contributed to (no authorisation)."""
    post.delete()
    release_hashtags(post)
    profile_increment(post.author_id, "posts_count", -1)
    if post.repost_of_id:
        increment(Post, post.repost_of_id, "repost_count", -1)


@transaction.atomic
def repost(*, actor: Any, post_id: Any, body: str = "") -> Post:
    """Repost (empty body) or quote (with body) a public post."""
    rate_limit("social_post", key=str(actor.pk))
    ensure_can_create(actor, "social.post")
    original = get_visible_post(actor, post_id)
    if original.is_pure_repost:
        original = get_visible_post(actor, original.repost_of_id)
    if original.visibility != Visibility.PUBLIC or original.status != ContentStatus.PUBLISHED:
        raise ValidationError("Only public posts can be reposted.", code="not_repostable")
    body = check_length(body, int(social_settings.get("POST_MAX_LENGTH", 5000)))
    status = screen_content(body, actor=actor, kind="post")
    try:
        with transaction.atomic():
            post = Post.objects.create(
                author=actor,
                body=body,
                repost_of=original,
                visibility=Visibility.PUBLIC,
                status=status,
                links=extract_links(body, limit=int(social_settings.get("MAX_LINKS_PER_POST", 5))),
            )
    except IntegrityError:
        raise Conflict("You have already reposted this.", code="already_reposted") from None
    increment(Post, original.pk, "repost_count", +1)
    profile_increment(actor.pk, "posts_count", +1)
    if body:
        sync_hashtags(post)
    if status == ContentStatus.PUBLISHED:
        if body:
            sync_post_mentions(post, notify=True)
        publish(
            events.POST_REPOSTED,
            {**_post_payload(post), "original_post_id": original.pk, "original_author_id": original.author_id},
            actor=actor,
        )
    return post


@transaction.atomic
def undo_repost(*, actor: Any, post_id: Any) -> None:
    pure = Post.objects.filter(author=actor, repost_of_id=post_id, body="").first()
    if pure is None:
        raise NotFound("Repost not found.")
    pure.delete()
    increment(Post, post_id, "repost_count", -1)
    profile_increment(actor.pk, "posts_count", -1)
