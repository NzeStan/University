from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.core.checks import Warning, register
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef, ScopeTypeDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.podcast import __version__
from university.podcast.constants import PODCAST_SCOPE


@register("university")
def check_media_library(app_configs: Any = None, **kwargs: Any) -> list[Warning]:
    from django.apps import apps

    if not apps.is_installed("university.podcast"):
        return []
    from university.core.media import get_media_library

    if get_media_library() is None:
        return [
            Warning(
                "university.podcast needs a media library for audio and video.",
                hint="Install university-media (INSTALLED_APPS += ['university.media']).",
                id="university_podcast.W001",
            )
        ]
    return []


class PodcastConfig(UniversityAppConfig):
    name = "university.podcast"
    label = "university_podcast"
    verbose_name = _("University Podcast")
    module_name = "podcast"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "PODCAST"
    api_prefix = ""
    api_urlconfs = {"v1": "university.podcast.api.v1.urls"}

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        from university.podcast.integrations import podcast_parents

        return [ScopeTypeDef(PODCAST_SCOPE, "A single podcast.", parent_resolver=podcast_parents)]

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("podcast.create", "Start podcasts (under the 'permission' creation policy).", scopes=("*",)),
            PermissionDef("podcast.manage", "Manage podcasts, episodes, transcripts and clips.", scopes=("*",)),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="podcast_manager",
                name="Podcast manager",
                scope_type="*",
                permissions=("podcast.*",),
                description="Runs podcasts for a scope (e.g. a campus radio station).",
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.podcast.content import EpisodeAdapter, ShowAdapter

        return [ShowAdapter(), EpisodeAdapter()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"podcast_create": "5/day"}

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.podcast.conf import podcast_settings
        from university.podcast.models import EpisodeDailyStat

        def cutoff() -> dt.datetime | None:
            days = podcast_settings.get("STATS_RETENTION_DAYS", 730)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="podcast.listening_stats",
                description="Daily play and completion counts.",
                setting="PODCAST.STATS_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(EpisodeDailyStat.objects.filter(date__lt=c.date()), dry),
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.podcast import integrations

        hooks.register(Hook.PERMISSIONS_IMPLICIT_GRANTS, integrations.implicit_grants)
        hooks.register(Hook.PERMISSIONS_IMPLICIT_SCOPES, integrations.implicit_scopes)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
