from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.opportunities import __version__


class OpportunitiesConfig(UniversityAppConfig):
    name = "university.opportunities"
    label = "university_opportunities"
    verbose_name = _("University Opportunities")
    module_name = "opportunities"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "OPPORTUNITIES"
    api_prefix = "opportunities/"
    api_urlconfs = {"v1": "university.opportunities.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("opportunities.verify", "Mark postings as from a verified employer.", sensitive=True),
            PermissionDef("opportunities.moderate", "Hide, restore or remove reported opportunities."),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="opportunities_curator",
                name="Opportunities curator",
                scope_type="platform",
                permissions=("opportunities.*",),
                description="Verifies employers and keeps opportunities free of scams.",
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.opportunities.content import OpportunityAdapter

        return [OpportunityAdapter()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"opportunity_create": "30/hour", "opportunity_apply": "60/hour"}

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.opportunities.services import purge_old_applications, retention_cutoff

        return [
            RetentionPolicy(
                name="opportunities.applications",
                description="Applications and CVs for opportunities that closed long ago.",
                setting="OPPORTUNITIES.APPLICATION_RETENTION_DAYS",
                cutoff=retention_cutoff,
                purge=purge_old_applications,
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.opportunities import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
