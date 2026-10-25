from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.permissions.models import Role, RoleAssignment
from university.permissions.services import invalidate_user_permissions


@admin.register(Role)
class RoleAdmin(admin.ModelAdmin):
    list_display = ("key", "name", "scope_type", "is_system")
    list_filter = ("scope_type", "is_system")
    search_fields = ("key", "name")

    def get_readonly_fields(self, request: Any, obj: Any = None) -> Any:
        return ("key", "scope_type", "permissions", "is_system") if obj and obj.is_system else ("is_system",)

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return bool(super().has_delete_permission(request, obj) and not (obj and obj.is_system))


@admin.register(RoleAssignment)
class RoleAssignmentAdmin(admin.ModelAdmin):
    list_display = ("user", "role", "scope_type", "scope_id", "created_at", "expires_at", "revoked_at")
    list_filter = ("role", "scope_type")
    search_fields = ("user__email", "user__handle", "scope_id")
    raw_id_fields = ("user", "granted_by", "revoked_by")
    readonly_fields = ("created_at", "updated_at")

    def save_model(self, request: Any, obj: Any, form: Any, change: bool) -> None:
        if not change:
            obj.granted_by = request.user
        super().save_model(request, obj, form, change)
        invalidate_user_permissions(obj.user_id)

    def delete_model(self, request: Any, obj: Any) -> None:
        user_id = obj.user_id
        super().delete_model(request, obj)
        invalidate_user_permissions(user_id)
