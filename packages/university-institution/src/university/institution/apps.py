from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db.models.signals import post_migrate
from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef, ScopeTypeDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.institution import __version__
from university.institution.constants import CAMPUS_SCOPE, INSTITUTION_SCOPE


def _campus_parents(campus_id: Any) -> list[tuple[str, Any]]:
    from university.institution.models import Campus

    institution_id = Campus.objects.filter(pk=campus_id).values_list("institution_id", flat=True).first()
    return [(INSTITUTION_SCOPE, institution_id)] if institution_id else []


class InstitutionConfig(UniversityAppConfig):
    name = "university.institution"
    label = "university_institution"
    verbose_name = _("University Institutions")
    module_name = "institution"
    module_version = __version__
    module_requires = ("core", "users", "security", "permissions", "audit")
    settings_namespace = "INSTITUTION"
    api_prefix = ""
    api_urlconfs = {"v1": "university.institution.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        post_migrate.connect(_seed_types, dispatch_uid="university.institution.seed_types")

    def get_content_adapters(self) -> list[Any]:
        # Display only: institutions are not moderatable (see content.py).
        from university.institution.content import AnnouncementAdapter, InstitutionAdapter

        return [InstitutionAdapter(), AnnouncementAdapter()]

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        return [
            ScopeTypeDef(INSTITUTION_SCOPE, "A single institution."),
            ScopeTypeDef(CAMPUS_SCOPE, "A campus of an institution.", parent_resolver=_campus_parents),
        ]

    def get_permissions(self) -> Iterable[PermissionDef]:
        both = ("platform", INSTITUTION_SCOPE)
        return [
            PermissionDef("institution.manage", "Create institutions and change their status/verification."),
            PermissionDef("institution.edit", "Edit an institution's profile.", scopes=both),
            PermissionDef("institution.structure.manage", "Manage campuses, units, programmes, sessions.", scopes=both),
            PermissionDef("institution.domains.manage", "Manage institution email domains.", scopes=both),
            PermissionDef("institution.memberships.view", "View an institution's members.", scopes=both),
            PermissionDef(
                "institution.memberships.verify", "Approve or reject memberships.", scopes=both, sensitive=True
            ),
            PermissionDef("institution.memberships.manage", "Suspend or revoke memberships.", scopes=both),
            PermissionDef(
                "institution.announcements.publish",
                "Write and publish official announcements for an institution.",
                scopes=both,
            ),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="institution_admin",
                name="Institution administrator",
                scope_type=INSTITUTION_SCOPE,
                permissions=(
                    "institution.edit",
                    "institution.structure.manage",
                    "institution.domains.manage",
                    "institution.memberships.*",
                    "institution.announcements.*",
                    "permissions.roles.view",
                    "permissions.roles.assign",
                ),
                description="Administers one institution and its members.",
            ),
            RoleDef(
                key="institution_communications",
                name="Communications officer",
                scope_type=INSTITUTION_SCOPE,
                permissions=("institution.announcements.publish",),
                description="Publishes official announcements for one institution.",
            ),
            RoleDef(
                key="institution_verifier",
                name="Membership verifier",
                scope_type=INSTITUTION_SCOPE,
                permissions=("institution.memberships.view", "institution.memberships.verify"),
                description="Reviews membership verification requests for one institution.",
            ),
            RoleDef(
                key="institution_platform_manager",
                name="Institution platform manager",
                scope_type="platform",
                permissions=("institution.*",),
                description="Manages every institution on the platform.",
            ),
        ]

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.institution.retention import document_cutoff, purge_verification_documents

        return [
            RetentionPolicy(
                name="institution.verification_documents",
                description="Uploaded verification documents after a decision.",
                setting="INSTITUTION.VERIFICATION_DOCUMENT_RETENTION_DAYS",
                cutoff=document_cutoff,
                purge=purge_verification_documents,
            )
        ]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"institution_join": "10/day", "institution_verification": "10/hour"}

    def register_hooks(self, hooks: HookRegistry) -> None:
        hooks.register(Hook.USER_PUBLIC_PROFILE, public_profile_affiliations)
        hooks.register(Hook.USER_EXPORT_DATA, export_memberships)
        hooks.register(Hook.USER_PURGE, purge_member_data)
        hooks.register(Hook.SCOPE_MEMBERSHIPS, scope_memberships)


def _seed_types(sender: Any, app_config: Any = None, **kwargs: Any) -> None:
    if app_config is None or app_config.label != "university_institution":
        return
    from university.institution.services import sync_institution_types

    sync_institution_types()


def public_profile_affiliations(target: Any, viewer: Any) -> dict[str, Any]:
    from university.institution.selectors import public_affiliations
    from university.users.services import get_privacy_settings

    if not get_privacy_settings(target).show_affiliations:
        return {}
    return {"institutions": public_affiliations(target)}


def export_memberships(user: Any) -> dict[str, Any]:
    from university.institution.models import InstitutionMembership

    return {
        "institution_memberships": [
            {
                "institution": m.institution.name,
                "role": m.role,
                "status": m.status,
                "identifier": m.identifier_hint,
                "entry_year": m.entry_year,
                "graduation_year": m.graduation_year,
                "verified_at": m.verified_at,
                "created_at": m.created_at,
            }
            for m in InstitutionMembership.objects.filter(user=user).select_related("institution")
        ]
    }


def scope_memberships(user: Any) -> list[tuple[str, Any]]:
    """Verified members belong to their institution's (and campus's) audience."""
    from university.institution.constants import InstitutionStatus, MembershipStatus
    from university.institution.models import InstitutionMembership

    rows = InstitutionMembership.objects.filter(
        user=user, status=MembershipStatus.VERIFIED, institution__status=InstitutionStatus.ACTIVE
    ).values_list("institution_id", "campus_id")
    scopes: list[tuple[str, Any]] = []
    for institution_id, campus_id in rows:
        scopes.append((INSTITUTION_SCOPE, institution_id))
        if campus_id:
            scopes.append((CAMPUS_SCOPE, campus_id))
    return scopes


def purge_member_data(user_id: Any) -> None:
    from university.institution.models import InstitutionMembership, VerificationRequest

    for request in VerificationRequest.objects.filter(membership__user_id=user_id).exclude(document=""):
        request.document.delete(save=False)
    VerificationRequest.objects.filter(membership__user_id=user_id).update(document="", evidence={}, email_hash="")
    InstitutionMembership.objects.filter(user_id=user_id).update(identifier_hash="", identifier_hint="")
