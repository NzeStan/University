from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import HealthCheck, RetentionPolicy
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.media import __version__


class MediaConfig(UniversityAppConfig):
    name = "university.media"
    label = "university_media"
    verbose_name = _("University Media")
    module_name = "media"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "MEDIA"
    api_prefix = "media/"
    api_urlconfs = {"v1": "university.media.api.v1.urls"}

    def get_media_library(self) -> Any:
        from university.media.library import Library

        return Library()

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"media_upload": "60/hour"}

    def get_health_checks(self) -> Iterable[HealthCheck]:
        def processing_flowing() -> bool:
            from university.media.models import AssetStatus, MediaAsset

            stuck = MediaAsset.objects.filter(
                status__in=[AssetStatus.PENDING, AssetStatus.PROCESSING],
                updated_at__lt=timezone.now() - dt.timedelta(hours=2),
            )
            return not stuck.exists()

        return [HealthCheck("media.processing", processing_flowing, critical=False)]

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.media.conf import media_settings
        from university.media.services import purge_failed, purge_orphans

        def orphan_cutoff() -> dt.datetime | None:
            hours = media_settings.get("ORPHAN_RETENTION_HOURS", 48)
            return None if hours is None else timezone.now() - dt.timedelta(hours=int(hours))

        def failed_cutoff() -> dt.datetime | None:
            days = media_settings.get("FAILED_RETENTION_DAYS", 7)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="media.orphans",
                description="Uploads never attached to anything (files deleted).",
                setting="MEDIA.ORPHAN_RETENTION_HOURS",
                cutoff=orphan_cutoff,
                purge=purge_orphans,
            ),
            RetentionPolicy(
                name="media.failed",
                description="Uploads that failed processing (files deleted).",
                setting="MEDIA.FAILED_RETENTION_DAYS",
                cutoff=failed_cutoff,
                purge=purge_failed,
            ),
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.media import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
