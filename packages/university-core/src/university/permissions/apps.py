from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.db.models.signals import post_migrate, post_save
from django.utils.translation import gettext_lazy as _

from university.core import __version__
from university.core.declarations import PermissionDef, RoleDef
from university.core.modules import UniversityAppConfig


class PermissionsConfig(UniversityAppConfig):
    name = "university.permissions"
    label = "university_permissions"
    verbose_name = _("University Permissions")
    module_name = "permissions"
    module_version = __version__
    module_requires = ("core", "audit")
    api_urlconfs = {"v1": "university.permissions.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        from university.permissions.models import Role

        post_migrate.connect(_sync_roles, dispatch_uid="university.permissions.sync_roles")
        post_save.connect(_role_changed, sender=Role, dispatch_uid="university.permissions.role_changed")

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("permissions.roles.view", "View roles and assignments.", scopes=("*",)),
            PermissionDef("permissions.roles.manage", "Create and edit custom roles."),
            PermissionDef("permissions.roles.assign", "Assign and revoke roles.", scopes=("*",), sensitive=True),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="platform_admin",
                name="Platform administrator",
                scope_type="platform",
                permissions=("*",),
                description="Holds every permission across the platform.",
            )
        ]


def _sync_roles(sender: Any, app_config: Any = None, **kwargs: Any) -> None:
    if app_config is None or app_config.label != "university_permissions":
        return
    from university.permissions.services import sync_system_roles

    sync_system_roles()


def _role_changed(sender: Any, **kwargs: Any) -> None:
    from university.permissions.services import invalidate_all_permissions

    invalidate_all_permissions()
