"""Creator verification: a creator asks, a reviewer (never themselves) decides."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.ratelimit import rate_limit
from university.creator import events
from university.creator.constants import ProfileStatus, RequestStatus, VerificationStatus
from university.creator.models import CreatorProfile, VerificationRequest
from university.creator.selectors import own_profile
from university.creator.services.profiles import screen
from university.permissions.services import authorize


def _payload(request: VerificationRequest, **extra: Any) -> dict[str, Any]:
    return {"request_id": request.pk, "profile_id": request.profile_id, "user_id": request.profile.user_id, **extra}


def _links(value: Iterable[Any]) -> list[str]:
    links = [str(v).strip()[:300] for v in value or [] if str(v).strip()]
    if len(links) > 10 or any(not link.lower().startswith("https://") for link in links):
        raise ValidationError(details={"links": ["Up to 10 https:// links."]})
    return links


@transaction.atomic
def request_verification(*, user: Any, statement: str, links: Iterable[Any] = ()) -> VerificationRequest:
    rate_limit("creator_verification", key=str(user.pk))
    profile = CreatorProfile.objects.select_for_update().get(pk=own_profile(user).pk)
    if profile.status != ProfileStatus.ACTIVE:
        raise Conflict("Activate your creator profile first.", code="profile_inactive")
    if profile.verification_status == VerificationStatus.VERIFIED:
        raise Conflict("You're already verified.", code="already_verified")
    statement = (statement or "").strip()
    if not 20 <= len(statement) <= 3000:
        raise ValidationError(details={"statement": ["Tell reviewers about yourself in 20 to 3000 characters."]})
    screen(statement, actor=user, kind="creator_verification")
    try:
        with transaction.atomic():
            request = VerificationRequest.objects.create(profile=profile, statement=statement, links=_links(links))
    except IntegrityError:
        raise Conflict("You already have a pending request.", code="request_pending") from None
    profile.verification_status = VerificationStatus.PENDING
    profile.save(update_fields=["verification_status", "updated_at"])
    audit("creator.verification.requested", actor=user, target=request, category="creator")
    publish(events.VERIFICATION_REQUESTED, _payload(request), actor=user)
    return request


@transaction.atomic
def withdraw_verification(*, user: Any) -> None:
    profile = own_profile(user)
    request = (
        VerificationRequest.objects.select_for_update().filter(profile=profile, status=RequestStatus.PENDING).first()
    )
    if request is None:
        raise NotFound("No pending request.")
    request.status = RequestStatus.WITHDRAWN
    request.save(update_fields=["status", "updated_at"])
    CreatorProfile.objects.filter(pk=profile.pk, verification_status=VerificationStatus.PENDING).update(
        verification_status=VerificationStatus.UNVERIFIED
    )


@transaction.atomic
def decide_verification(*, actor: Any, request_id: Any, approve: bool, reason: str = "") -> VerificationRequest:
    authorize(actor, "creator.verify", audit_denial=True)
    request = VerificationRequest.objects.select_for_update().select_related("profile").filter(pk=request_id).first()
    if request is None:
        raise NotFound("Request not found.")
    if request.profile.user_id == actor.pk:
        raise PermissionDenied("You can't review your own request.", code="self_review")
    if request.status != RequestStatus.PENDING:
        raise Conflict("This request was already decided.", code="already_decided")
    now = timezone.now()
    request.status = RequestStatus.APPROVED if approve else RequestStatus.REJECTED
    request.reviewed_by = actor
    request.reviewed_at = now
    request.decision_reason = reason[:500]
    request.save(update_fields=["status", "reviewed_by", "reviewed_at", "decision_reason", "updated_at"])
    profile = request.profile
    profile.verification_status = VerificationStatus.VERIFIED if approve else VerificationStatus.UNVERIFIED
    profile.verified_at = now if approve else None
    profile.save(update_fields=["verification_status", "verified_at", "updated_at"])
    audit(
        f"creator.verification.{'approved' if approve else 'rejected'}",
        actor=actor,
        target=request,
        category="creator",
        metadata={"reason": reason[:500]},
    )
    publish(events.VERIFICATION_APPROVED if approve else events.VERIFICATION_REJECTED, _payload(request), actor=actor)
    return request


@transaction.atomic
def revoke_verification(*, actor: Any, profile_id: Any, reason: str) -> CreatorProfile:
    authorize(actor, "creator.verify", audit_denial=True)
    profile = CreatorProfile.objects.select_for_update().filter(pk=profile_id).first()
    if profile is None:
        raise NotFound("Creator not found.")
    if profile.verification_status != VerificationStatus.VERIFIED:
        raise Conflict("This creator isn't verified.", code="not_verified")
    if not (reason or "").strip():
        raise ValidationError(details={"reason": ["Explain why."]})
    profile.verification_status = VerificationStatus.REVOKED
    profile.verified_at = None
    profile.save(update_fields=["verification_status", "verified_at", "updated_at"])
    audit(
        "creator.verification.revoked",
        actor=actor,
        target=profile,
        category="creator",
        metadata={"reason": reason[:500]},
    )
    publish(events.VERIFICATION_REVOKED, {"profile_id": profile.pk, "user_id": profile.user_id}, actor=actor)
    return profile
