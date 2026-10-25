from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.core.models import IdempotencyRecord, WebhookEvent


class ReadOnlyAdmin(admin.ModelAdmin):
    """Base admin for operational records that must not be edited by hand."""

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(WebhookEvent)
class WebhookEventAdmin(ReadOnlyAdmin):
    list_display = ("provider", "external_id", "event_type", "status", "attempts", "created_at")
    list_filter = ("provider", "status")
    search_fields = ("external_id",)
    exclude = ("payload",)
    date_hierarchy = "created_at"


@admin.register(IdempotencyRecord)
class IdempotencyRecordAdmin(ReadOnlyAdmin):
    list_display = ("scope", "key", "user", "status", "response_status", "created_at")
    list_filter = ("scope", "status")
    exclude = ("response_body",)
    raw_id_fields = ("user",)
