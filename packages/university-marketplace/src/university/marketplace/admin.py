from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.marketplace.models import Listing, MarketCategory, Order, Review, SellerProfile


@admin.register(MarketCategory)
class MarketCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "parent", "is_active", "position")
    list_editable = ("is_active", "position")


@admin.register(SellerProfile)
class SellerProfileAdmin(admin.ModelAdmin):
    list_display = ("store_name", "user", "rating_count", "sales_count")
    search_fields = ("store_name", "user__handle")
    raw_id_fields = ("user",)
    readonly_fields = ("rating_sum", "rating_count", "sales_count")


@admin.register(Listing)
class ListingAdmin(admin.ModelAdmin):
    list_display = ("title", "seller", "price_minor", "currency", "quantity", "status", "hidden_at")
    list_filter = ("status", "visibility", "category")
    search_fields = ("title",)
    raw_id_fields = ("seller",)
    readonly_fields = ("hidden_at", "hidden_reason", "published_at")

    def get_queryset(self, request: Any) -> Any:
        return Listing.all_objects.all()


@admin.register(Order)
class OrderAdmin(admin.ModelAdmin):
    """Read-only: orders change through audited services (stock and escrow depend on it)."""

    list_display = ("reference", "title", "total_minor", "currency", "status", "payment_method", "created_at")
    list_filter = ("status", "payment_method", "fulfilment")
    search_fields = ("reference",)
    exclude = ("delivery_details",)

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ("seller", "rating", "hidden_at", "created_at")
    list_filter = ("rating",)
    raw_id_fields = ("order", "reviewer", "seller", "listing")
