from __future__ import annotations

import datetime as dt
from collections.abc import Iterable

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import RetentionPolicy
from university.core.events import EventBus
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.trending import __version__


class TrendingConfig(UniversityAppConfig):
    name = "university.trending"
    label = "university_trending"
    verbose_name = _("University Trending")
    module_name = "trending"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "TRENDING"
    api_prefix = "trending/"
    api_urlconfs = {"v1": "university.trending.api.v1.urls"}

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.trending.conf import trending_settings
        from university.trending.models import TrendingSignal

        def cutoff() -> dt.datetime | None:
            hours = trending_settings.get("SIGNAL_RETENTION_HOURS", 168)
            return None if hours is None else timezone.now() - dt.timedelta(hours=int(hours))

        return [
            RetentionPolicy(
                name="trending.signals",
                description="Hourly engagement buckets used to compute trending.",
                setting="TRENDING.SIGNAL_RETENTION_HOURS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(TrendingSignal.objects.filter(hour__lt=c), dry),
            )
        ]

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.trending.conf import trending_settings
        from university.trending.services import handle_event

        for name in trending_settings.get("SIGNALS") or {}:
            bus.subscribe(name, handle_event)

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.trending.services import scores_for

        hooks.register(Hook.CONTENT_TRENDING_SCORES, scores_for)
