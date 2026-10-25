from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.analytics import __version__
from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.events import EventBus
from university.core.modules import UniversityAppConfig


class AnalyticsConfig(UniversityAppConfig):
    name = "university.analytics"
    label = "university_analytics"
    verbose_name = _("University Analytics")
    module_name = "analytics"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "ANALYTICS"
    api_prefix = "analytics/"
    api_urlconfs = {"v1": "university.analytics.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [PermissionDef("analytics.view", "View aggregate analytics for a scope or the platform.", scopes=("*",))]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="analytics_viewer",
                name="Analytics viewer",
                scope_type="*",
                permissions=("analytics.view",),
                description="Reads aggregate analytics (e.g. an institution's leadership).",
            )
        ]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"analytics_view": "600/hour"}

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.analytics.conf import analytics_settings
        from university.analytics.models import MetricDaily
        from university.core.retention import delete_queryset

        def cutoff() -> dt.datetime | None:
            days = analytics_settings.get("RETENTION_DAYS", 1095)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="analytics.daily_metrics",
                description="Daily aggregate counters.",
                setting="ANALYTICS.RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(MetricDaily.objects.filter(date__lt=c.date()), dry),
            )
        ]

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.analytics.ingestion import handle_event

        bus.subscribe("*", handle_event)
