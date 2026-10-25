"""Helpers shared by social services."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db.models import F
from django.db.models.functions import Greatest

from university.core.exceptions import NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction
from university.social.constants import ContentStatus
from university.social.models import SocialProfile

ACTIVE = "active"


def increment(model: Any, pk: Any, field: str, delta: int = 1) -> None:
    """Atomic counter update that never goes below zero."""
    if delta >= 0:
        model.objects.filter(pk=pk).update(**{field: F(field) + delta})
    else:
        model.objects.filter(pk=pk).update(**{field: Greatest(F(field) + delta, 0)})


def ensure_profiles(*user_ids: Any) -> None:
    existing = set(SocialProfile.objects.filter(user_id__in=user_ids).values_list("user_id", flat=True))
    SocialProfile.objects.bulk_create(
        [SocialProfile(user_id=uid) for uid in set(user_ids) - existing], ignore_conflicts=True
    )


def profile_increment(user_id: Any, field: str, delta: int = 1) -> None:
    ensure_profiles(user_id)
    if delta >= 0:
        SocialProfile.objects.filter(user_id=user_id).update(**{field: F(field) + delta})
    else:
        SocialProfile.objects.filter(user_id=user_id).update(**{field: Greatest(F(field) + delta, 0)})


def active_user(user_id: Any) -> Any:
    user = get_user_model().objects.filter(pk=user_id, status=ACTIVE).first()
    if user is None:
        raise NotFound("User not found.")
    return user


def ensure_can_interact(actor: Any, target: Any, action: str) -> None:
    if not hooks.allows(Hook.USER_CAN_INTERACT, actor, target, action):
        raise PermissionDenied("You can't do that.", code="interaction_not_allowed")


def check_length(text: str, limit: int, field: str = "body") -> str:
    text = (text or "").strip()
    if len(text) > limit:
        raise ValidationError(details={field: [f"Ensure this field has no more than {limit} characters."]})
    return text


def screen_content(text: str, *, actor: Any, kind: str) -> str:
    """Run the anti-spam provider; return the initial content status."""
    if not text:
        return ContentStatus.PUBLISHED
    verdict = get_spam_filter().check(text, actor=actor, context={"kind": kind})
    if verdict.action == SpamAction.REJECT:
        raise ValidationError(
            "This content was rejected by our spam filter.",
            code="content_rejected",
            details={"reasons": list(verdict.reasons)},
        )
    return ContentStatus.PENDING_REVIEW if verdict.action == SpamAction.REVIEW else ContentStatus.PUBLISHED
