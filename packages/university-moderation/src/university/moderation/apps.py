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
from university.moderation import __version__


class ModerationConfig(UniversityAppConfig):
    name = "university.moderation"
    label = "university_moderation"
    verbose_name = _("University Moderation")
    module_name = "moderation"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "MODERATION"
    api_prefix = "moderation/"
    api_urlconfs = {"v1": "university.moderation.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        post_migrate.connect(_seed, dispatch_uid="university.moderation.seed")

    def get_permissions(self) -> Iterable[PermissionDef]:
        anywhere = ("*",)
        return [
            PermissionDef("moderation.cases.view", "View moderation cases.", scopes=anywhere),
            PermissionDef("moderation.cases.act", "Act on moderation cases.", scopes=anywhere),
            PermissionDef("moderation.appeals.decide", "Decide appeals.", scopes=anywhere),
            PermissionDef("moderation.users.restrict", "Restrict users from creating content."),
            PermissionDef(
                "moderation.reports.view_reporters", "See who filed reports.", scopes=anywhere, sensitive=True
            ),
            PermissionDef("moderation.rules.manage", "Manage automated moderation rules."),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="platform_moderator",
                name="Platform moderator",
                scope_type="platform",
                permissions=("moderation.cases.*", "moderation.appeals.decide", "moderation.users.restrict"),
                description="Reviews reports and acts on content across the platform.",
            ),
            RoleDef(
                key="scoped_moderator",
                name="Scoped moderator",
                scope_type="*",
                permissions=("moderation.cases.view", "moderation.cases.act", "moderation.appeals.decide"),
                description="Moderates content within one scope (an institution, campus or community).",
            ),
            RoleDef(
                key="trust_safety_lead",
                name="Trust & safety lead",
                scope_type="platform",
                permissions=("moderation.*", "users.suspend", "users.ban"),
                description="Full moderation authority, including account sanctions.",
            ),
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.moderation.adapters import UserAccountAdapter

        return [UserAccountAdapter()]

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.moderation.conf import moderation_settings
        from university.moderation.constants import CaseStatus
        from university.moderation.models import ModerationCase

        def cutoff() -> dt.datetime | None:
            days = moderation_settings.get("RESOLVED_CASE_RETENTION_DAYS", 730)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="moderation.resolved_cases",
                description="Resolved cases, their reports and evidence snapshots (actions are kept).",
                setting="MODERATION.RESOLVED_CASE_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(
                    ModerationCase.objects.exclude(status=CaseStatus.OPEN).filter(resolved_at__lt=c), dry
                ),
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.moderation import integrations

        hooks.register(Hook.USER_CAN_CREATE_CONTENT, integrations.can_create_content)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)


def _seed(sender: Any, app_config: Any = None, **kwargs: Any) -> None:
    if app_config is None or app_config.label != "university_moderation":
        return
    from university.moderation.services import sync_reasons_and_rules

    sync_reasons_and_rules()
