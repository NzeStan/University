from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils.text import slugify

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import NotFound, ValidationError
from university.institution import events
from university.institution.conf import institution_settings
from university.institution.models import Institution, InstitutionDomain, InstitutionType
from university.institution.services.common import apply_fields, institution_scope, save_validated, validate_choice
from university.institution.verification import list_providers
from university.permissions.services import authorize

EDITABLE_FIELDS = (
    "name",
    "short_name",
    "type",
    "ownership",
    "country",
    "region",
    "city",
    "website",
    "description",
    "founded_year",
    "verification_methods",
    "metadata",
)
PLATFORM_ONLY_FIELDS = ("status", "is_verified", "slug")


def sync_institution_types() -> int:
    """Seed configured institution types (existing ones are left untouched)."""
    created = 0
    for position, entry in enumerate(institution_settings.get("INSTITUTION_TYPES", [])):
        _, was_created = InstitutionType.objects.get_or_create(
            key=entry["key"],
            defaults={"name": entry["name"], "description": entry.get("description", ""), "ordering": position},
        )
        created += int(was_created)
    return created


def _validate(data: dict[str, Any]) -> None:
    if "ownership" in data:
        validate_choice(data["ownership"], institution_settings.get("OWNERSHIP_TYPES"), "ownership")
    if "country" in data:
        data["country"] = str(data["country"]).upper()
    if "verification_methods" in data:
        methods = data["verification_methods"] or []
        unknown = [m for m in methods if m not in list_providers()]
        if unknown:
            raise ValidationError(details={"verification_methods": [f"Unknown methods: {', '.join(unknown)}"]})


@transaction.atomic
def create_institution(*, actor: Any, data: dict[str, Any]) -> Institution:
    authorize(actor, "institution.manage", audit_denial=True)
    data = dict(data)
    _validate(data)
    slug = data.pop("slug", None) or slugify(data.get("short_name") or data.get("name", ""))[:100]
    institution = Institution(slug=slug)
    apply_fields(institution, data, (*EDITABLE_FIELDS, *PLATFORM_ONLY_FIELDS))
    save_validated(institution, conflict_message="An institution with this slug already exists.")
    audit("institution.created", actor=actor, target=institution, scope=("institution", institution.pk))
    publish(events.INSTITUTION_CREATED, {"institution_id": institution.pk}, actor=actor)
    return institution


@transaction.atomic
def update_institution(*, actor: Any, institution: Institution, data: dict[str, Any]) -> Institution:
    data = dict(data)
    if set(data) & set(PLATFORM_ONLY_FIELDS):
        authorize(actor, "institution.manage", audit_denial=True)
        allowed = (*EDITABLE_FIELDS, *PLATFORM_ONLY_FIELDS)
    else:
        authorize(actor, "institution.edit", institution_scope(institution), audit_denial=True)
        allowed = EDITABLE_FIELDS
    _validate(data)
    changed = apply_fields(institution, data, allowed)
    if changed:
        save_validated(institution, conflict_message="An institution with this slug already exists.")
        audit(
            "institution.updated",
            actor=actor,
            target=institution,
            scope=("institution", institution.pk),
            metadata={"fields": changed},
        )
        publish(events.INSTITUTION_UPDATED, {"institution_id": institution.pk, "fields": changed}, actor=actor)
    return institution


@transaction.atomic
def add_domain(
    *, actor: Any, institution: Institution, domain: str, allow_subdomains: bool = False, verified: bool | None = None
) -> InstitutionDomain:
    """Register an email domain. Only platform managers may mark it verified."""
    authorize(actor, "institution.domains.manage", institution_scope(institution), audit_denial=True)
    from university.permissions.services import has_permission

    is_platform_manager = has_permission(actor, "institution.manage")
    item = InstitutionDomain(
        institution=institution,
        domain=domain.strip().lower().lstrip("@"),
        allow_subdomains=allow_subdomains,
        is_verified=bool(verified) and is_platform_manager if verified is not None else is_platform_manager,
    )
    save_validated(item, conflict_message="This domain is already registered.")
    audit(
        "institution.domain.added",
        actor=actor,
        target=item,
        scope=("institution", institution.pk),
        metadata={"domain": item.domain, "verified": item.is_verified},
    )
    return item


@transaction.atomic
def remove_domain(*, actor: Any, institution: Institution, domain_id: Any) -> None:
    authorize(actor, "institution.domains.manage", institution_scope(institution), audit_denial=True)
    item = InstitutionDomain.objects.filter(pk=domain_id, institution=institution).first()
    if item is None:
        raise NotFound("Domain not found.")
    item.delete()
    audit(
        "institution.domain.removed",
        actor=actor,
        target_type="university_institution.institutiondomain",
        target_id=domain_id,
        scope=("institution", institution.pk),
    )
