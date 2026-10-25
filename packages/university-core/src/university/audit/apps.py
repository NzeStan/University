from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.utils.translation import gettext_lazy as _

from university.core import __version__
from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig


class AuditConfig(UniversityAppConfig):
    name = "university.audit"
    label = "university_audit"
    verbose_name = _("University Audit")
    module_name = "audit"
    module_version = __version__
    module_requires = ("core",)
    api_urlconfs = {"v1": "university.audit.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("audit.view", "View the platform audit log.", sensitive=True),
            PermissionDef("audit.verify", "Verify audit log integrity."),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="security_auditor",
                name="Security auditor",
                scope_type="platform",
                permissions=("audit.*",),
                description="Read-only access to the audit log.",
            )
        ]

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.audit.models import AuditLog
        from university.core.retention import cutoff_days

        def purge(cutoff: Any, dry_run: bool) -> int:
            qs = AuditLog.objects.filter(created_at__lt=cutoff)
            return qs.count() if dry_run else qs._purge()

        return [
            RetentionPolicy(
                name="audit.log",
                description="Audit log entries.",
                setting="RETENTION.AUDIT_LOG_DAYS",
                cutoff=cutoff_days("AUDIT_LOG_DAYS"),
                purge=purge,
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        hooks.register(Hook.USER_EXPORT_DATA, export_user_activity)


def export_user_activity(user: Any) -> dict[str, Any]:
    from university.audit.selectors import activity_for_user

    return {
        "security_activity": [
            {
                "action": e.action,
                "outcome": e.outcome,
                "created_at": e.created_at.isoformat(),
                "ip_address": e.ip_address,
                "user_agent": e.user_agent,
            }
            for e in activity_for_user(user)[:1000]
        ]
    }
