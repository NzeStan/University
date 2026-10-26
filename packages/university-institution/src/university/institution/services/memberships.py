"""Institution memberships and their verification.

Lifecycle::

    request_membership ─► pending ──start_verification──► (provider)
                             │                                │
                             │◄──── awaiting_user ◄───────────┤ complete_verification
                             │                                │
                             ├──── review (approve) ──────────┴─► verified ─► suspended / revoked / left
                             └──── review (reject) ───────────────► rejected
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.institution import events
from university.institution.conf import institution_settings
from university.institution.constants import (
    OPEN_MEMBERSHIP_STATUSES,
    OPEN_VERIFICATION_STATUSES,
    InstitutionStatus,
    MembershipStatus,
    VerificationStatus,
)
from university.institution.models import (
    AcademicUnit,
    Campus,
    Institution,
    InstitutionMembership,
    Level,
    Programme,
    VerificationRequest,
)
from university.institution.services.common import ensure_same_institution, institution_scope
from university.institution.verification import get_provider
from university.permissions.services import authorize

DETAIL_FIELDS = ("campus", "academic_unit", "programme", "level", "entry_year", "graduation_year")


def _audit(action: str, actor: Any, membership: InstitutionMembership, **metadata: Any) -> None:
    audit(
        action,
        actor=actor,
        target=membership,
        scope=("institution", membership.institution_id),
        metadata={"role": membership.role, **metadata},
    )


def _payload(membership: InstitutionMembership) -> dict[str, Any]:
    return {
        "membership_id": membership.pk,
        "user_id": membership.user_id,
        "institution_id": membership.institution_id,
        "role": membership.role,
    }


def _set_status(membership: InstitutionMembership, status: str, reason: str = "") -> None:
    membership.status = status
    membership.status_reason = reason[:255]
    membership.status_changed_at = timezone.now()
    fields = ["status", "status_reason", "status_changed_at", "updated_at"]
    if status not in (MembershipStatus.VERIFIED, MembershipStatus.PENDING) and membership.is_primary:
        membership.is_primary = False
        fields.append("is_primary")
    membership.save(update_fields=fields)


def allowed_methods(institution: Institution) -> list[str]:
    configured = institution_settings.get("VERIFICATION_PROVIDERS", {})
    methods = institution.verification_methods or institution_settings.get("DEFAULT_VERIFICATION_METHODS", [])
    return [m for m in methods if m in configured]


# ---------------------------------------------------------------- joining
def _validate_details(institution: Institution, details: Mapping[str, Any]) -> None:
    ensure_same_institution(
        institution.pk,
        campus=details.get("campus"),
        academic_unit=details.get("academic_unit"),
        programme=details.get("programme"),
        level=details.get("level"),
    )
    entry, graduation = details.get("entry_year"), details.get("graduation_year")
    if entry and graduation and graduation < entry:
        raise ValidationError(details={"graduation_year": ["Cannot be before the entry year."]})


@transaction.atomic
def request_membership(
    *,
    user: Any,
    institution: Institution,
    role: str,
    campus: Campus | None = None,
    academic_unit: AcademicUnit | None = None,
    programme: Programme | None = None,
    level: Level | None = None,
    entry_year: int | None = None,
    graduation_year: int | None = None,
) -> InstitutionMembership:
    if institution.status != InstitutionStatus.ACTIVE or institution.is_deleted:
        raise NotFound("Institution not found.")
    if role not in institution_settings.get("MEMBERSHIP_ROLES", []):
        raise ValidationError(details={"role": ["Unknown membership role."]})
    details = {
        "campus": campus,
        "academic_unit": academic_unit,
        "programme": programme,
        "level": level,
        "entry_year": entry_year,
        "graduation_year": graduation_year,
    }
    _validate_details(institution, details)

    open_memberships = InstitutionMembership.objects.filter(user=user, status__in=OPEN_MEMBERSHIP_STATUSES)
    if (
        not institution_settings.get("ALLOW_MULTIPLE_INSTITUTIONS", True)
        and open_memberships.exclude(institution=institution).exists()
    ):
        raise ValidationError("You can only belong to one institution.", code="single_institution_only")
    if open_memberships.count() >= int(institution_settings.get("MAX_ACTIVE_MEMBERSHIPS_PER_USER", 5)):
        raise ValidationError("You have reached the maximum number of memberships.", code="membership_limit")

    auto_verify = role in institution_settings.get("AUTO_VERIFY_ROLES", [])
    membership = InstitutionMembership(
        user=user,
        institution=institution,
        role=role,
        status=MembershipStatus.VERIFIED if auto_verify else MembershipStatus.PENDING,
        verified_at=timezone.now() if auto_verify else None,
        verification_method="auto" if auto_verify else "",
        is_primary=not InstitutionMembership.objects.filter(user=user, is_primary=True).exists(),
        **details,
    )
    try:
        with transaction.atomic():
            membership.save()
    except IntegrityError:
        raise Conflict("You already have this membership.", code="membership_exists") from None
    _audit("institution.membership.requested", user, membership)
    publish(events.MEMBERSHIP_REQUESTED, _payload(membership), actor=user)
    if auto_verify:
        publish(events.MEMBERSHIP_VERIFIED, _payload(membership), actor=user)
        publish(events.INSTITUTION_JOINED, _payload(membership), actor=user)
    return membership


def _own_membership(user: Any, membership_id: Any) -> InstitutionMembership:
    membership = (
        InstitutionMembership.objects.select_for_update(of=("self",))
        .select_related("institution")
        .filter(pk=membership_id, user=user)
        .first()
    )
    if membership is None:
        raise NotFound("Membership not found.")
    return membership


# ----------------------------------------------------------- verification
def _approve(membership: InstitutionMembership, *, method: str, actor: Any = None, reason: str = "") -> None:
    membership.verified_at = timezone.now()
    membership.verified_by = actor
    membership.verification_method = method
    membership.save(update_fields=["verified_at", "verified_by", "verification_method", "updated_at"])
    _set_status(membership, MembershipStatus.VERIFIED, reason)
    _audit("institution.membership.verified", actor, membership, method=method)
    publish(events.MEMBERSHIP_VERIFIED, _payload(membership), actor=actor)
    publish(events.INSTITUTION_JOINED, _payload(membership), actor=actor)


@transaction.atomic
def start_verification(
    *, user: Any, membership_id: Any, method: str, data: Mapping[str, Any] | None = None, file: Any = None
) -> VerificationRequest:
    membership = _own_membership(user, membership_id)
    if membership.status != MembershipStatus.PENDING:
        raise Conflict("Only pending memberships can be verified.", code="not_pending")
    if method not in allowed_methods(membership.institution):
        raise ValidationError(details={"method": ["This verification method is not available."]})
    # Starting again supersedes any open attempt.
    VerificationRequest.objects.filter(membership=membership, status__in=OPEN_VERIFICATION_STATUSES).update(
        status=VerificationStatus.CANCELLED, decided_at=timezone.now()
    )
    provider = get_provider(method)
    request = provider.start(membership=membership, data=data or {}, file=file)
    publish(
        events.VERIFICATION_STARTED,
        {**_payload(membership), "verification_id": request.pk, "method": method},
        actor=user,
    )
    if request.status == VerificationStatus.APPROVED:
        _approve(membership, method=method)
    return request


@transaction.atomic
def complete_verification(*, user: Any, verification_id: Any, data: Mapping[str, Any]) -> VerificationRequest:
    request = (
        VerificationRequest.objects.select_for_update(of=("self",))
        .select_related("membership", "membership__institution")
        .filter(pk=verification_id, membership__user=user)
        .first()
    )
    if request is None:
        raise NotFound("Verification not found.")
    if request.status != VerificationStatus.AWAITING_USER:
        raise Conflict("This verification cannot be completed.", code="not_awaiting_user")
    if request.expires_at and request.expires_at <= timezone.now():
        VerificationRequest.objects.filter(pk=request.pk).update(status=VerificationStatus.EXPIRED)
        raise ValidationError("This verification has expired. Start again.", code="verification_expired")
    request = get_provider(request.method).complete(request=request, data=data)
    if request.status == VerificationStatus.APPROVED:
        request.decided_at = timezone.now()
        try:
            with transaction.atomic():
                request.save(update_fields=["status", "decided_at", "updated_at"])
        except IntegrityError:
            raise ValidationError("Unable to verify with this email address.", code="email_unavailable") from None
        _approve(request.membership, method=request.method)
    else:
        request.save()
    return request


# ------------------------------------------------------------- reviewing
def _membership_in(institution: Institution, membership_id: Any) -> InstitutionMembership:
    membership = (
        InstitutionMembership.objects.select_for_update().filter(pk=membership_id, institution=institution).first()
    )
    if membership is None:
        raise NotFound("Membership not found.")
    return membership


@transaction.atomic
def review_membership(
    *, actor: Any, institution: Institution, membership_id: Any, approve: bool, reason: str = ""
) -> InstitutionMembership:
    authorize(actor, "institution.memberships.verify", institution_scope(institution), audit_denial=True)
    membership = _membership_in(institution, membership_id)
    if membership.user_id == actor.pk:
        raise PermissionDenied("You cannot review your own membership.", code="self_review")
    if membership.status != MembershipStatus.PENDING:
        raise Conflict("Only pending memberships can be reviewed.", code="not_pending")
    open_request = (
        VerificationRequest.objects.filter(membership=membership, status__in=OPEN_VERIFICATION_STATUSES)
        .order_by("-created_at")
        .first()
    )
    decision = VerificationStatus.APPROVED if approve else VerificationStatus.REJECTED
    if open_request is not None:
        VerificationRequest.objects.filter(pk=open_request.pk).update(
            status=decision, decided_at=timezone.now(), decided_by=actor, decision_reason=reason[:255]
        )
    if approve:
        _approve(membership, method=open_request.method if open_request else "manual", actor=actor, reason=reason)
    else:
        _set_status(membership, MembershipStatus.REJECTED, reason)
        _audit("institution.membership.rejected", actor, membership, reason=reason)
        publish(events.MEMBERSHIP_REJECTED, _payload(membership), actor=actor)
    return membership


@transaction.atomic
def suspend_membership(
    *, actor: Any, institution: Institution, membership_id: Any, reason: str
) -> InstitutionMembership:
    authorize(actor, "institution.memberships.manage", institution_scope(institution), audit_denial=True)
    membership = _membership_in(institution, membership_id)
    if membership.status != MembershipStatus.VERIFIED:
        raise Conflict("Only verified memberships can be suspended.", code="not_verified")
    _set_status(membership, MembershipStatus.SUSPENDED, reason)
    _audit("institution.membership.suspended", actor, membership, reason=reason)
    publish(events.MEMBERSHIP_SUSPENDED, _payload(membership), actor=actor)
    return membership


@transaction.atomic
def revoke_membership(
    *, actor: Any, institution: Institution, membership_id: Any, reason: str
) -> InstitutionMembership:
    authorize(actor, "institution.memberships.manage", institution_scope(institution), audit_denial=True)
    membership = _membership_in(institution, membership_id)
    if membership.status not in OPEN_MEMBERSHIP_STATUSES:
        raise Conflict("This membership is not active.", code="not_active")
    _set_status(membership, MembershipStatus.REVOKED, reason)
    _audit("institution.membership.revoked", actor, membership, reason=reason)
    publish(events.MEMBERSHIP_REVOKED, _payload(membership), actor=actor)
    return membership


# ------------------------------------------------------------ self-service
@transaction.atomic
def leave_membership(*, user: Any, membership_id: Any) -> InstitutionMembership:
    membership = _own_membership(user, membership_id)
    if membership.status not in (MembershipStatus.PENDING, MembershipStatus.VERIFIED):
        raise Conflict("This membership cannot be left.", code="not_active")
    VerificationRequest.objects.filter(membership=membership, status__in=OPEN_VERIFICATION_STATUSES).update(
        status=VerificationStatus.CANCELLED
    )
    _set_status(membership, MembershipStatus.LEFT)
    _audit("institution.membership.left", user, membership)
    publish(events.MEMBERSHIP_LEFT, _payload(membership), actor=user)
    return membership


@transaction.atomic
def set_primary_membership(*, user: Any, membership_id: Any) -> InstitutionMembership:
    membership = _own_membership(user, membership_id)
    if membership.status not in (MembershipStatus.PENDING, MembershipStatus.VERIFIED):
        raise Conflict("Only active memberships can be primary.", code="not_active")
    InstitutionMembership.objects.filter(user=user, is_primary=True).exclude(pk=membership.pk).update(is_primary=False)
    InstitutionMembership.objects.filter(pk=membership.pk).update(is_primary=True)
    membership.is_primary = True
    return membership


@transaction.atomic
def update_membership_details(*, user: Any, membership_id: Any, data: Mapping[str, Any]) -> InstitutionMembership:
    """Members may update study details (progression), never role or status."""
    membership = _own_membership(user, membership_id)
    unknown = set(data) - set(DETAIL_FIELDS)
    if unknown:
        raise ValidationError(details={f: ["This field cannot be changed."] for f in sorted(unknown)})
    if membership.status not in (MembershipStatus.PENDING, MembershipStatus.VERIFIED):
        raise Conflict("This membership cannot be changed.", code="not_active")
    merged = {field: data.get(field, getattr(membership, field)) for field in DETAIL_FIELDS}
    _validate_details(membership.institution, merged)
    changed = [f for f in data if getattr(membership, f) != data[f]]
    for field in changed:
        setattr(membership, field, data[field])
    if changed:
        membership.save(update_fields=[*changed, "updated_at"])
        _audit("institution.membership.updated", user, membership, fields=changed)
    return membership
