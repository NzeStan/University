from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.moderation.models import (
    ModerationAction,
    ModerationAppeal,
    ModerationCase,
    ModerationRule,
    Report,
    ReportReason,
    UserRestriction,
)


class ReadOnly(admin.ModelAdmin):
    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(ReportReason)
class ReportReasonAdmin(admin.ModelAdmin):
    list_display = ("label", "key", "severity", "requires_details", "is_active", "ordering")
    list_editable = ("severity", "is_active", "ordering")


@admin.register(ModerationRule)
class ModerationRuleAdmin(admin.ModelAdmin):
    list_display = ("name", "rule_type", "action", "is_active")
    readonly_fields = ("key", "rule_type")


class ReportInline(admin.TabularInline):
    model = Report
    extra = 0
    fields = ("reason", "details", "created_at")
    readonly_fields = fields
    can_delete = False


@admin.register(ModerationCase)
class ModerationCaseAdmin(ReadOnly):
    """Read-only: act through the API so actions are authorised and audited.

    The author column is deliberately absent (anonymous content)."""

    list_display = ("id", "content_type", "status", "priority", "report_count", "auto_actioned", "created_at")
    list_filter = ("status", "content_type", "source")
    inlines = (ReportInline,)
    exclude = ("target_author",)


@admin.register(ModerationAction)
class ModerationActionAdmin(ReadOnly):
    list_display = ("action", "content_type", "automated", "created_at", "reversed_at")
    list_filter = ("action", "automated")
    exclude = ("target_user",)


@admin.register(ModerationAppeal)
class ModerationAppealAdmin(ReadOnly):
    list_display = ("id", "status", "created_at", "decided_at")
    list_filter = ("status",)
    exclude = ("appellant",)


@admin.register(UserRestriction)
class UserRestrictionAdmin(ReadOnly):
    list_display = ("user", "kind", "ends_at", "lifted_at")
    list_filter = ("kind",)
