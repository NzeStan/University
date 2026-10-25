from __future__ import annotations

from typing import Any

from django.contrib import admin, messages

from university.security.models import APIKey, ExternalIdentity, LoginAttempt, UserSession
from university.security.services.sessions import revoke_session


class NoAddAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: Any) -> bool:
        return False


@admin.register(UserSession)
class UserSessionAdmin(NoAddAdmin):
    list_display = (
        "id",
        "user",
        "auth_method",
        "device_name",
        "ip_address",
        "created_at",
        "last_seen_at",
        "revoked_at",
    )
    list_filter = ("auth_method", "revoked_reason")
    search_fields = ("user__email", "user__handle", "device_name")
    raw_id_fields = ("user",)
    readonly_fields = [f.name for f in UserSession._meta.fields]
    actions = ["revoke_selected"]

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    @admin.action(description="Revoke selected sessions", permissions=["view"])
    def revoke_selected(self, request: Any, queryset: Any) -> None:
        for session in queryset:
            revoke_session(session, actor=request.user, reason="revoked_by_admin")
        self.message_user(request, "Selected sessions revoked.", messages.SUCCESS)


@admin.register(APIKey)
class APIKeyAdmin(NoAddAdmin):
    list_display = ("name", "lookup", "user", "created_at", "last_used_at", "expires_at", "revoked_at")
    search_fields = ("name", "lookup", "user__email")
    raw_id_fields = ("user",)
    readonly_fields = ("lookup", "key_hash", "created_at", "last_used_at")
    exclude = ("key_hash",)


@admin.register(LoginAttempt)
class LoginAttemptAdmin(NoAddAdmin):
    list_display = ("created_at", "successful", "failure_reason", "user", "ip_address")
    list_filter = ("successful", "failure_reason")
    search_fields = ("user__email", "ip_address")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in LoginAttempt._meta.fields]

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(ExternalIdentity)
class ExternalIdentityAdmin(NoAddAdmin):
    list_display = ("provider", "subject", "user", "created_at", "last_login_at")
    list_filter = ("provider",)
    search_fields = ("subject", "email", "user__email")
    raw_id_fields = ("user",)
