from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.db.models.signals import post_migrate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.marketplace import __version__


def _seed_categories(sender: Any, app_config: Any = None, **kwargs: Any) -> None:
    if app_config is None or app_config.label != "university_marketplace":
        return
    from university.marketplace.services import sync_categories

    sync_categories()


class MarketplaceConfig(UniversityAppConfig):
    name = "university.marketplace"
    label = "university_marketplace"
    verbose_name = _("University Marketplace")
    module_name = "marketplace"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "MARKETPLACE"
    api_prefix = "marketplace/"
    api_urlconfs = {"v1": "university.marketplace.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        post_migrate.connect(_seed_categories, dispatch_uid="university.marketplace.seed_categories")

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("marketplace.disputes.resolve", "Decide order disputes (refund or release).", sensitive=True),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="marketplace_mediator",
                name="Marketplace mediator",
                scope_type="platform",
                permissions=("marketplace.disputes.resolve",),
                description="Resolves disputes between buyers and sellers.",
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.marketplace.content import ListingAdapter, ReviewAdapter

        return [ListingAdapter(), ReviewAdapter()]

    def get_payable_adapters(self) -> list[Any]:
        from university.marketplace.payables import OrderPayable

        return [OrderPayable()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"marketplace_listing_create": "30/day", "marketplace_order": "30/hour"}

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.marketplace.conf import marketplace_settings
        from university.marketplace.models import Order

        def cutoff() -> dt.datetime | None:
            days = marketplace_settings.get("DELIVERY_DETAILS_RETENTION_DAYS", 30)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        def erase(c: dt.datetime, dry: bool) -> int:
            qs = Order.objects.filter(closed_at__lt=c).exclude(delivery_details="")
            return qs.count() if dry else qs.update(delivery_details="")

        return [
            RetentionPolicy(
                name="marketplace.delivery_details",
                description="Delivery addresses and phone numbers on closed orders (erased, order kept).",
                setting="MARKETPLACE.DELIVERY_DETAILS_RETENTION_DAYS",
                cutoff=cutoff,
                purge=erase,
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.marketplace import integrations

        hooks.register(Hook.USER_PUBLIC_PROFILE, integrations.public_profile)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
