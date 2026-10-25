from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.social import __version__


class SocialConfig(UniversityAppConfig):
    name = "university.social"
    label = "university_social"
    verbose_name = _("University Social")
    module_name = "social"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "SOCIAL"
    api_prefix = "social/"
    api_urlconfs = {"v1": "university.social.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            # "*" scopes: grantable at any audience scope (institution, campus, community).
            PermissionDef("social.content.moderate", "Hide, restore and remove posts and comments.", scopes=("*",)),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="social_moderator",
                name="Social moderator",
                scope_type="platform",
                permissions=("social.content.moderate",),
                description="Moderates posts and comments across the platform.",
            )
        ]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {
            "social_post": "30/hour",
            "social_comment": "120/hour",
            "social_reaction": "600/hour",
            "social_follow": "200/day",
            "social_media_upload": "60/hour",
        }

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.social.retention import orphan_media_cutoff, purge_orphan_media

        return [
            RetentionPolicy(
                name="social.orphan_media",
                description="Uploaded media never attached to a post.",
                setting="SOCIAL.ORPHAN_MEDIA_HOURS",
                cutoff=orphan_media_cutoff,
                purge=purge_orphan_media,
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.social.content import SocialCommentAdapter, SocialPostAdapter

        return [SocialPostAdapter(), SocialCommentAdapter()]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.social import integrations

        hooks.register(Hook.USER_CAN_VIEW_PROFILE, integrations.can_view_profile)
        hooks.register(Hook.USER_CAN_INTERACT, integrations.can_interact)
        hooks.register(Hook.USER_PUBLIC_PROFILE, integrations.public_profile)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
