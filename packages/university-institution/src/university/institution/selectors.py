"""Read-side queries for institutions. Filters are whitelisted."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet

from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.institution.constants import InstitutionStatus, MembershipStatus
from university.institution.models import (
    AcademicSession,
    AcademicUnit,
    Campus,
    Institution,
    InstitutionDomain,
    InstitutionMembership,
    Level,
    Programme,
    VerificationRequest,
)
from university.institution.services.common import institution_scope
from university.permissions.services import has_permission


def can_manage(user: Any, institution: Institution, code: str) -> bool:
    return has_permission(user, code, institution_scope(institution))


def list_institutions(params: Mapping[str, Any], *, include_inactive: bool = False) -> QuerySet[Institution]:
    qs = Institution.objects.select_related("type")
    if not include_inactive:
        qs = qs.filter(status=InstitutionStatus.ACTIVE)
    if params.get("country"):
        qs = qs.filter(country=str(params["country"]).upper()[:2])
    if params.get("type"):
        qs = qs.filter(type__key=str(params["type"])[:50])
    if params.get("verified") in ("true", "1"):
        qs = qs.filter(is_verified=True)
    if params.get("q"):
        term = str(params["q"]).strip()[:100]
        qs = qs.filter(Q(name__icontains=term) | Q(short_name__icontains=term) | Q(city__icontains=term))
    return qs.order_by("name", "id")


def get_institution(institution_id: Any, *, user: Any = None) -> Institution:
    """Active institutions are public; inactive ones only to their managers."""
    if not is_valid_uuid(institution_id):
        raise NotFound("Institution not found.")
    institution = Institution.objects.select_related("type").filter(pk=institution_id).first()
    if institution is None:
        raise NotFound("Institution not found.")
    if institution.status != InstitutionStatus.ACTIVE and not (
        user is not None and can_manage(user, institution, "institution.edit")
    ):
        raise NotFound("Institution not found.")
    return institution


def campuses(institution: Institution) -> QuerySet[Campus]:
    return institution.campuses.filter(is_active=True)


def academic_units(institution: Institution, params: Mapping[str, Any]) -> QuerySet[AcademicUnit]:
    qs = institution.academic_units.filter(is_active=True).select_related("parent")
    if params.get("type"):
        qs = qs.filter(unit_type=str(params["type"])[:32])
    parent = params.get("parent")
    if parent == "root":
        qs = qs.filter(parent__isnull=True)
    elif parent and is_valid_uuid(parent):
        qs = qs.filter(parent_id=parent)
    return qs


def programmes(institution: Institution, params: Mapping[str, Any]) -> QuerySet[Programme]:
    qs = institution.programmes.filter(is_active=True).select_related("academic_unit")
    unit = params.get("academic_unit")
    if unit and is_valid_uuid(unit):
        qs = qs.filter(academic_unit_id=unit)
    if params.get("qualification_level"):
        qs = qs.filter(qualification_level=str(params["qualification_level"])[:32])
    return qs


def levels(institution: Institution, params: Mapping[str, Any]) -> QuerySet[Level]:
    qs = institution.levels.all()
    programme = params.get("programme")
    if programme and is_valid_uuid(programme):
        qs = qs.filter(Q(programme_id=programme) | Q(programme__isnull=True))
    return qs


def sessions(institution: Institution) -> QuerySet[AcademicSession]:
    return institution.academic_sessions.prefetch_related("semesters")


def verified_domains(institution: Institution) -> QuerySet[InstitutionDomain]:
    return institution.domains.filter(is_verified=True)


def user_memberships(user: Any) -> QuerySet[InstitutionMembership]:
    return (
        InstitutionMembership.objects.filter(user=user)
        .select_related("institution", "campus", "academic_unit", "programme", "level")
        .order_by("-is_primary", "-created_at")
    )


def institution_memberships(institution: Institution, params: Mapping[str, Any]) -> QuerySet[InstitutionMembership]:
    qs = InstitutionMembership.objects.filter(institution=institution).select_related(
        "user", "campus", "academic_unit", "programme", "level"
    )
    if params.get("status") in MembershipStatus.values:
        qs = qs.filter(status=params["status"])
    if params.get("role"):
        qs = qs.filter(role=str(params["role"])[:32])
    return qs.order_by("-created_at", "-id")


def verification_requests(membership: InstitutionMembership) -> QuerySet[VerificationRequest]:
    return membership.verification_requests.order_by("-created_at")


def public_affiliations(user: Any) -> list[dict[str, Any]]:
    return [
        {
            "institution_id": str(m.institution_id),
            "name": m.institution.name,
            "short_name": m.institution.short_name,
            "role": m.role,
        }
        for m in InstitutionMembership.objects.filter(
            user=user, status=MembershipStatus.VERIFIED, institution__status=InstitutionStatus.ACTIVE
        ).select_related("institution")
    ]
