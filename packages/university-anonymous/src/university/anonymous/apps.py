from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.utils.translation import gettext_lazy as _

from university.anonymous import __version__
from university.core.declarations import PermissionDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig


class AnonymousConfig(UniversityAppConfig):
    name = "university.anonymous"
    label = "university_anonymous"
    verbose_name = _("University Anonymous")
    module_name = "anonymous"
    module_version = __version__
    # Moderation is required: never run an anonymous system without abuse controls.
    module_requires = ("core", "users", "permissions", "audit", "moderation")
    settings_namespace = "ANONYMOUS"
    api_prefix = "anonymous/"
    api_urlconfs = {"v1": "university.anonymous.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        from university.anonymous import checks  # noqa: F401

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef(
                "anonymous.identity.reveal",
                "Request and retrieve the identity behind anonymous content.",
                sensitive=True,
            ),
            PermissionDef(
                "anonymous.identity.reveal_approve",
                "Approve identity reveal requests (second person).",
                sensitive=True,
            ),
            PermissionDef(
                "anonymous.authors.sanction",
                "Apply account sanctions to authors of anonymous content.",
                scopes=("*",),
                sensitive=True,
            ),
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.anonymous.content import AnonymousCommentAdapter, AnonymousPostAdapter

        return [AnonymousPostAdapter(), AnonymousCommentAdapter()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {
            "anonymous_post": "5/hour",
            "anonymous_post_daily": "20/day",
            "anonymous_comment": "30/hour",
            "anonymous_reaction": "300/hour",
            "anonymous_reveal": "10/day",
        }

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.anonymous import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
