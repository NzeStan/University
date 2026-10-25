from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.db.models.signals import post_migrate
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.events import EventBus
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.creator import __version__


def _seed_categories(sender: Any, app_config: Any = None, **kwargs: Any) -> None:
    if app_config is None or app_config.label != "university_creator":
        return
    from university.creator.services import sync_categories

    sync_categories()


class CreatorConfig(UniversityAppConfig):
    name = "university.creator"
    label = "university_creator"
    verbose_name = _("University Creator")
    module_name = "creator"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "CREATOR"
    api_prefix = ""
    api_urlconfs = {"v1": "university.creator.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        post_migrate.connect(_seed_categories, dispatch_uid="university.creator.seed_categories")

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("creator.verify", "Review creator verification and confirm linked accounts."),
            PermissionDef(
                "creator.campaigns.manage",
                "Run sponsorship campaigns (for a scope, or anywhere under the 'permission' policy).",
                scopes=("*",),
            ),
            PermissionDef("creator.analytics.view", "View any creator's analytics (support staff)."),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="creator_reviewer",
                name="Creator reviewer",
                scope_type="platform",
                permissions=("creator.verify",),
                description="Reviews verification requests and confirms linked accounts.",
            ),
            RoleDef(
                key="campaign_manager",
                name="Campaign manager",
                scope_type="*",
                permissions=("creator.campaigns.manage",),
                description="Runs sponsorship campaigns for a scope (e.g. a students' union).",
            ),
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.creator.content import CampaignAdapter

        return [CampaignAdapter()]

    def get_payable_adapters(self) -> list[Any]:
        from university.creator.payables import ParticipationPayable

        return [ParticipationPayable()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {
            "creator_verification": "3/day",
            "creator_link_account": "30/day",
            "creator_verify_account": "20/hour",
            "creator_campaign_create": "10/day",
            "creator_campaign_apply": "30/day",
            "creator_campaign_invite": "100/day",
        }

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.creator.conf import creator_settings
        from university.creator.models import CreatorDailyStat, LinkedAccountSnapshot

        def cutoff() -> dt.datetime | None:
            days = creator_settings.get("ANALYTICS_RETENTION_DAYS", 730)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="creator.analytics",
                description="Daily creator analytics counters.",
                setting="CREATOR.ANALYTICS_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(CreatorDailyStat.objects.filter(date__lt=c.date()), dry),
            ),
            RetentionPolicy(
                name="creator.follower_snapshots",
                description="Daily follower counts of linked accounts.",
                setting="CREATOR.ANALYTICS_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(LinkedAccountSnapshot.objects.filter(date__lt=c.date()), dry),
            ),
        ]

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.creator.handlers import HANDLERS, handle_event

        for name in HANDLERS:
            bus.subscribe(name, handle_event)

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.creator import integrations

        hooks.register(Hook.USER_PUBLIC_PROFILE, integrations.public_profile)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
