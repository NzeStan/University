"""Read-only admin: money moves only through audited services."""

from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.payments.models import LedgerEntry, PaymentIntent, Payout, Refund


class ReadOnlyAdmin(admin.ModelAdmin):
    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False

    def has_delete_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(PaymentIntent)
class PaymentIntentAdmin(ReadOnlyAdmin):
    list_display = ("reference", "purpose", "amount_minor", "currency", "provider", "status", "paid_at")
    list_filter = ("status", "provider", "purpose", "currency")
    search_fields = ("reference", "provider_transaction_id", "object_id")


@admin.register(Refund)
class RefundAdmin(ReadOnlyAdmin):
    list_display = ("reference", "intent", "amount_minor", "status", "attempts", "created_at")
    list_filter = ("status",)


@admin.register(Payout)
class PayoutAdmin(ReadOnlyAdmin):
    list_display = ("payee", "amount_minor", "currency", "status", "processed_at")
    list_filter = ("status", "currency")


@admin.register(LedgerEntry)
class LedgerEntryAdmin(ReadOnlyAdmin):
    list_display = ("created_at", "account", "amount_minor", "currency", "kind", "group")
    list_filter = ("kind", "currency")
    search_fields = ("account",)
