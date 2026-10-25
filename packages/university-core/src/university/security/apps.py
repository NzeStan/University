from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from django.utils.translation import gettext_lazy as _

from university.core import __version__
from university.core.declarations import PermissionDef, RetentionPolicy
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig


class SecurityConfig(UniversityAppConfig):
    name = "university.security"
    label = "university_security"
    verbose_name = _("University Security")
    module_name = "security"
    module_version = __version__
    module_requires = ("core", "audit", "users")
    api_urlconfs = {"v1": "university.security.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        from university.core.api.schema import SPECTACULAR_INSTALLED

        if SPECTACULAR_INSTALLED:
            from university.security import schema  # noqa: F401

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("security.sessions.manage", "Revoke other users' sessions.", sensitive=True),
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        hooks.register(Hook.USER_EXPORT_DATA, export_security_data)

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from django.db.models import Q

        from university.core.retention import cutoff_days, delete_queryset
        from university.security.models import LoginAttempt, OTPChallenge, UserSession

        return [
            RetentionPolicy(
                name="security.login_attempts",
                description="Login attempt records.",
                setting="RETENTION.LOGIN_ATTEMPT_DAYS",
                cutoff=cutoff_days("LOGIN_ATTEMPT_DAYS"),
                purge=lambda c, dry: delete_queryset(LoginAttempt.objects.filter(created_at__lt=c), dry),
            ),
            RetentionPolicy(
                name="security.otp_challenges",
                description="Expired or consumed one-time code challenges.",
                setting="RETENTION.OTP_CHALLENGE_DAYS",
                cutoff=cutoff_days("OTP_CHALLENGE_DAYS"),
                purge=lambda c, dry: delete_queryset(OTPChallenge.objects.filter(created_at__lt=c), dry),
            ),
            RetentionPolicy(
                name="security.sessions",
                description="Revoked or expired sessions and their refresh tokens.",
                setting="RETENTION.REVOKED_SESSION_DAYS",
                cutoff=cutoff_days("REVOKED_SESSION_DAYS"),
                purge=lambda c, dry: delete_queryset(
                    UserSession.objects.filter(Q(revoked_at__lt=c) | Q(expires_at__lt=c)), dry
                ),
            ),
        ]


def export_security_data(user: Any) -> dict[str, Any]:
    from university.security.models import APIKey, ExternalIdentity, UserSession

    return {
        "sessions": [
            {
                "id": s.pk,
                "auth_method": s.auth_method,
                "device_name": s.device_name,
                "user_agent": s.user_agent,
                "ip_address": s.ip_address,
                "created_at": s.created_at,
                "last_seen_at": s.last_seen_at,
                "revoked_at": s.revoked_at,
            }
            for s in UserSession.objects.filter(user=user).order_by("-created_at")[:500]
        ],
        "api_keys": [
            {"id": k.pk, "name": k.name, "scopes": k.scopes, "created_at": k.created_at, "revoked_at": k.revoked_at}
            for k in APIKey.objects.filter(user=user)
        ],
        "external_identities": [
            {"provider": i.provider, "email": i.email, "created_at": i.created_at}
            for i in ExternalIdentity.objects.filter(user=user)
        ],
    }
