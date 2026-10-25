from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.notifications.models import Delivery, Notification, PushDevice


class DeliveryInline(admin.TabularInline):
    model = Delivery
    extra = 0
    can_delete = False
    fields = ("channel", "status", "attempts", "reason", "sent_at")
    readonly_fields = fields

    def has_add_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(Notification)
class NotificationAdmin(admin.ModelAdmin):
    list_display = ("verb", "category", "recipient", "actor_count", "in_app", "read_at", "last_activity_at")
    list_filter = ("category", "verb", "in_app")
    raw_id_fields = ("recipient", "actor")
    readonly_fields = ("recipient", "verb", "category", "actor", "actor_count", "target_type", "target_id", "data")
    inlines = (DeliveryInline,)

    def has_add_permission(self, request: Any) -> bool:
        return False


@admin.register(Delivery)
class DeliveryAdmin(admin.ModelAdmin):
    list_display = ("channel", "status", "attempts", "reason", "sent_at", "created_at")
    list_filter = ("channel", "status", "reason")
    raw_id_fields = ("notification",)

    def has_add_permission(self, request: Any) -> bool:
        return False


@admin.register(PushDevice)
class PushDeviceAdmin(admin.ModelAdmin):
    list_display = ("user", "platform", "name", "last_seen_at", "disabled_at", "disabled_reason")
    list_filter = ("platform", "disabled_reason")
    raw_id_fields = ("user",)
    # The token is a credential for the device: never displayed.
    exclude = ("token", "token_hash")
    readonly_fields = ("platform", "last_seen_at")

    def has_add_permission(self, request: Any) -> bool:
        return False
