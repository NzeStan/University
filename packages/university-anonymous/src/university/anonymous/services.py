"""Anonymous content services.

Privacy rules every service here follows:

* never write an audit entry, event or log line that links a user to an item
  (audit logs are append-only — a link written there could never be erased);
* store authorship only as :class:`~university.anonymous.models.Authorship`
  (keyed owner token + encrypted identity);
* respond identically to authors and others except where the author is the
  one asking about their own item.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone

from university.anonymous import events
from university.anonymous.conf import anonymous_settings
from university.anonymous.identity import owner_token, owns, pseudonym_for, seal_identity, thread_token
from university.anonymous.models import (
    AnonymousComment,
    AnonymousPost,
    AnonymousReaction,
    Authorship,
    ContentStatus,
    HiddenPost,
)
from university.anonymous.selectors import authorship, get_visible_post, in_audience
from university.core.audiences import ensure_can_post_to, is_member
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import NotFound, PermissionDenied, ValidationError
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction
from university.core.ratelimit import rate_limit


def _gate(user: Any, content_type: str) -> None:
    if anonymous_settings.get("REQUIRE_VERIFIED_EMAIL", True) and not user.email_verified_at:
        raise PermissionDenied("Verify your email address to post anonymously.", code="email_not_verified")
    min_age = int(anonymous_settings.get("MIN_ACCOUNT_AGE_HOURS", 24))
    if user.created_at > timezone.now() - dt.timedelta(hours=min_age):
        raise PermissionDenied("Your account is too new to post anonymously.", code="account_too_new")
    ensure_can_create(user, content_type)


def _screen(text: str, user: Any, kind: str) -> str:
    verdict = get_spam_filter().check(text, actor=user, context={"kind": kind, "anonymous": True})
    if verdict.action == SpamAction.REJECT:
        raise ValidationError("This content was rejected by our spam filter.", code="content_rejected")
    return ContentStatus.PENDING_REVIEW if verdict.action == SpamAction.REVIEW else ContentStatus.PUBLISHED


def _text(value: str, limit: int) -> str:
    value = (value or "").strip()
    if not value:
        raise ValidationError(details={"body": ["This field may not be blank."]})
    if len(value) > limit:
        raise ValidationError(details={"body": [f"Ensure this field has no more than {limit} characters."]})
    return value


def _record_authorship(kind: str, object_id: Any, user: Any) -> None:
    Authorship.objects.create(
        kind=kind,
        object_id=object_id,
        owner_token=owner_token(kind, object_id, user.pk),
        identity_cipher=seal_identity(user.pk),
    )


def _post_payload(post: AnonymousPost) -> dict[str, Any]:
    return {"post_id": post.pk, "scope_type": post.scope_type, "scope_id": post.scope_id}


# ------------------------------------------------------------------ posts
@transaction.atomic
def create_post(
    *, author: Any, body: str, visibility: str, audience_id: Any = None, comments_enabled: bool = True
) -> AnonymousPost:
    _gate(author, "anonymous.post")
    rate_limit("anonymous_post", key=str(author.pk))
    rate_limit("anonymous_post_daily", key=str(author.pk))
    allowed = anonymous_settings.get("ALLOWED_VISIBILITIES", [])
    if visibility not in allowed:
        raise ValidationError(details={"visibility": [f"Must be one of: {', '.join(allowed)}."]})
    scope_type, scope_id = "", ""
    if visibility != "public":
        if not audience_id:
            raise ValidationError(details={"audience_id": ["Required for this visibility."]})
        if not is_member(author, visibility, audience_id):
            raise PermissionDenied("You are not a member of this audience.", code="not_audience_member")
        ensure_can_post_to(author, visibility, audience_id, "anonymous.post")
        scope_type, scope_id = visibility, str(audience_id)
    body = _text(body, int(anonymous_settings.get("POST_MAX_LENGTH", 3000)))
    status = _screen(body, author, "anonymous.post")
    post = AnonymousPost.objects.create(
        body=body,
        visibility=visibility,
        scope_type=scope_type,
        scope_id=scope_id,
        status=status,
        comments_enabled=comments_enabled,
    )
    _record_authorship(Authorship.Kind.POST, post.pk, author)
    if status == ContentStatus.PUBLISHED:
        publish(events.POST_CREATED, _post_payload(post))
    return post


def _owned(kind: str, model: Any, user: Any, object_id: Any) -> Any:
    obj = model.objects.filter(pk=object_id).first()
    record = authorship(kind, object_id) if obj is not None else None
    if obj is None or record is None or not owns(kind, object_id, user, record.owner_token):
        raise NotFound()
    return obj


@transaction.atomic
def delete_own_post(*, user: Any, post_id: Any) -> None:
    post = _owned(Authorship.Kind.POST, AnonymousPost, user, post_id)
    post.delete()
    publish(events.POST_DELETED, _post_payload(post))


# --------------------------------------------------------------- comments
def _pseudonym(post: AnonymousPost, user: Any, token: str) -> tuple[str, bool]:
    post_record = authorship(Authorship.Kind.POST, post.pk)
    is_op = bool(post_record and owns(Authorship.Kind.POST, post.pk, user, post_record.owner_token))
    if is_op and anonymous_settings.get("SHOW_OP_LABEL", True):
        return "OP", True
    existing = (
        AnonymousComment.all_objects.filter(post=post, thread_token=token).values_list("pseudonym", flat=True).first()
    )
    if existing:
        return existing, is_op
    name = pseudonym_for(token)
    taken = set(
        AnonymousComment.all_objects.filter(post=post, pseudonym__startswith=name)
        .exclude(thread_token=token)
        .values_list("pseudonym", flat=True)
    )
    candidate, n = name, 2
    while candidate in taken:
        candidate, n = f"{name} {n}", n + 1
    return candidate, is_op


@transaction.atomic
def create_comment(*, author: Any, post_id: Any, body: str) -> AnonymousComment:
    _gate(author, "anonymous.comment")
    rate_limit("anonymous_comment", key=str(author.pk))
    post = get_visible_post(author, post_id)
    post = AnonymousPost.objects.select_for_update().get(pk=post.pk)  # serialise positions per thread
    if post.status != ContentStatus.PUBLISHED or not post.comments_enabled:
        raise PermissionDenied("Comments are turned off for this post.", code="comments_disabled")
    if post.scope_type:
        ensure_can_post_to(author, post.scope_type, post.scope_id, "anonymous.comment")
    body = _text(body, int(anonymous_settings.get("COMMENT_MAX_LENGTH", 1000)))
    status = _screen(body, author, "anonymous.comment")
    token = thread_token(post.pk, author.pk)
    pseudonym, is_op = _pseudonym(post, author, token)
    position = AnonymousComment.all_objects.filter(post=post).count() + 1
    comment = AnonymousComment.objects.create(
        post=post, body=body, pseudonym=pseudonym, thread_token=token, is_op=is_op, status=status, position=position
    )
    _record_authorship(Authorship.Kind.COMMENT, comment.pk, author)
    AnonymousPost.objects.filter(pk=post.pk).update(comment_count=F("comment_count") + 1)
    if status == ContentStatus.PUBLISHED:
        publish(events.COMMENT_CREATED, {"comment_id": comment.pk, "post_id": post.pk})
    return comment


@transaction.atomic
def delete_own_comment(*, user: Any, comment_id: Any) -> None:
    comment = _owned(Authorship.Kind.COMMENT, AnonymousComment, user, comment_id)
    comment.delete()
    AnonymousPost.objects.filter(pk=comment.post_id).update(comment_count=Greatest(F("comment_count") - 1, 0))
    publish(events.COMMENT_DELETED, {"comment_id": comment.pk, "post_id": comment.post_id})


# ------------------------------------------------------- reactions / hide
@transaction.atomic
def react(*, user: Any, post_id: Any, kind: str) -> None:
    if kind not in anonymous_settings.get("REACTION_TYPES", []):
        raise ValidationError(details={"kind": ["Unknown reaction."]})
    rate_limit("anonymous_reaction", key=str(user.pk))
    post = get_visible_post(user, post_id)
    if post.status != ContentStatus.PUBLISHED:
        raise NotFound()
    updated = AnonymousReaction.objects.filter(post=post, user=user).update(kind=kind)
    if updated:
        return
    try:
        with transaction.atomic():
            AnonymousReaction.objects.create(post=post, user=user, kind=kind)
    except IntegrityError:
        AnonymousReaction.objects.filter(post=post, user=user).update(kind=kind)
        return
    AnonymousPost.objects.filter(pk=post.pk).update(reaction_count=F("reaction_count") + 1)


@transaction.atomic
def unreact(*, user: Any, post_id: Any) -> None:
    deleted, _ = AnonymousReaction.objects.filter(post_id=post_id, user=user).delete()
    if deleted:
        AnonymousPost.objects.filter(pk=post_id).update(reaction_count=Greatest(F("reaction_count") - 1, 0))


@transaction.atomic
def hide_for_me(*, user: Any, post_id: Any) -> None:
    post = get_visible_post(user, post_id)
    HiddenPost.objects.get_or_create(post=post, user=user)


@transaction.atomic
def unhide_for_me(*, user: Any, post_id: Any) -> None:
    HiddenPost.objects.filter(post_id=post_id, user=user).delete()


__all__ = [
    "create_comment",
    "create_post",
    "delete_own_comment",
    "delete_own_post",
    "hide_for_me",
    "in_audience",
    "react",
    "unhide_for_me",
    "unreact",
]
