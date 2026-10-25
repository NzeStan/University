from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.audit.models import AuditLog


class SecurityCategoryFilter(admin.SimpleListFilter):
    title = "security events"
    parameter_name = "security"

    def lookups(self, request: Any, model_admin: Any) -> list[tuple[str, str]]:
        return [("1", "Security & authentication only")]

    def queryset(self, request: Any, queryset: Any) -> Any:
        if self.value() == "1":
            return queryset.filter(category__in=["auth", "security"])
        return queryset


@admin.register(AuditLog)
class AuditLogAdmin(admin.ModelAdmin):
    list_display = ("created_at", "action", "outcome", "actor_ref", "target_type", "target_id", "ip_address")
    list_filter = (SecurityCategoryFilter, "category", "outcome", "action")
    search_fields = ("action", "actor_ref", "target_id", "request_id")
    date_hierarchy = "created_at"
    readonly_fields = [f.name for f in AuditLog._meta.fields]
    show_full_result_count = False

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False
