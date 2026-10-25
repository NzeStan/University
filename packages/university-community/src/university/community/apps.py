from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.community import __version__
from university.community.constants import COMMUNITY_SCOPE
from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef, ScopeTypeDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig


class CommunityConfig(UniversityAppConfig):
    name = "university.community"
    label = "university_community"
    verbose_name = _("University Communities")
    module_name = "community"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "COMMUNITY"
    api_prefix = ""
    api_urlconfs = {"v1": "university.community.api.v1.urls"}

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        from university.community.integrations import community_parents

        return [ScopeTypeDef(COMMUNITY_SCOPE, "A community.", parent_resolver=community_parents)]

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef(
                "community.create",
                "Create communities (required under the 'permission' policy and for official communities).",
                scopes=("*",),
            ),
            PermissionDef("community.manage", "Edit, archive and recognise communities.", scopes=("*",)),
            PermissionDef(
                "community.members.manage", "Manage members, requests, roles and invitations.", scopes=("*",)
            ),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="community_manager",
                name="Community manager",
                scope_type="*",
                permissions=("community.*",),
                description="Manages every community within a scope (e.g. an institution's communities).",
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.community.content import CommunityAdapter

        return [CommunityAdapter()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"community_create": "5/day", "community_join_code": "30/hour"}

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.community.conf import community_settings
        from university.community.models import CommunityInviteLink
        from university.core.retention import delete_queryset

        def cutoff() -> dt.datetime | None:
            days = community_settings.get("EXPIRED_INVITE_LINK_RETENTION_DAYS", 30)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="community.expired_invite_links",
                description="Invite links that expired or were revoked.",
                setting="COMMUNITY.EXPIRED_INVITE_LINK_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(CommunityInviteLink.objects.filter(expires_at__lt=c), dry),
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.community import integrations

        hooks.register(Hook.SCOPE_MEMBERSHIPS, integrations.scope_memberships)
        hooks.register(Hook.AUDIENCE_CAN_POST, integrations.can_post)
        hooks.register(Hook.PERMISSIONS_IMPLICIT_GRANTS, integrations.implicit_grants)
        hooks.register(Hook.PERMISSIONS_IMPLICIT_SCOPES, integrations.implicit_scopes)
        hooks.register(Hook.USER_PUBLIC_PROFILE, integrations.public_profile)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
