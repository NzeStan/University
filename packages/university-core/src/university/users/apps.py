from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _

from university.core import __version__
from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.modules import UniversityAppConfig


class UsersConfig(UniversityAppConfig):
    name = "university.users"
    label = "university_users"
    verbose_name = _("University Users")
    module_name = "users"
    module_version = __version__
    # The security app (same distribution) is used lazily, keeping the
    # declared dependency graph acyclic: security -> users -> permissions.
    module_requires = ("core", "audit", "permissions")
    api_urlconfs = {"v1": "university.users.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("users.view_private", "View private profiles and account details.", sensitive=True),
            PermissionDef("users.suspend", "Suspend and reactivate accounts."),
            PermissionDef("users.ban", "Ban accounts."),
            PermissionDef("users.delete", "Delete accounts."),
            PermissionDef("users.restore", "Restore deleted accounts within the grace period."),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="user_manager",
                name="User manager",
                scope_type="platform",
                permissions=("users.*",),
                description="Manages account status across the platform.",
            )
        ]

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.users.services.lifecycle import deletion_cutoff, purge_expired_deleted_users

        return [
            RetentionPolicy(
                name="users.deleted_accounts",
                description="Anonymise accounts deleted longer ago than the grace period.",
                setting="USERS.DELETION_GRACE_PERIOD_DAYS",
                cutoff=deletion_cutoff,
                purge=purge_expired_deleted_users,
            )
        ]
