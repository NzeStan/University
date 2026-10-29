from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RoleDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.promotions import __version__


class PromotionsConfig(UniversityAppConfig):
    name = "university.promotions"
    label = "university_promotions"
    verbose_name = _("University Promotions")
    module_name = "promotions"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "PROMOTIONS"
    api_prefix = "promotions/"
    api_urlconfs = {"v1": "university.promotions.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [PermissionDef("promotions.review", "Approve or reject adverts and boosts before they run.")]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="ads_reviewer",
                name="Ads reviewer",
                scope_type="platform",
                permissions=("promotions.review",),
                description="Reviews adverts and boosts against the advertising policy.",
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.promotions.content import CampaignAdapter

        return [CampaignAdapter()]

    def get_payable_adapters(self) -> list[Any]:
        from university.promotions.payables import CampaignPayable

        return [CampaignPayable()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"promotions_serve": "600/min", "promotions_track": "1200/min"}

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.promotions import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
