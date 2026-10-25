from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.creator.models import Campaign, CreatorCategory, CreatorProfile, LinkedAccount, VerificationRequest


@admin.register(CreatorCategory)
class CreatorCategoryAdmin(admin.ModelAdmin):
    list_display = ("name", "key", "is_active", "position")
    list_editable = ("is_active", "position")


class LinkedAccountInline(admin.TabularInline):
    model = LinkedAccount
    extra = 0
    fields = ("provider", "handle", "ownership", "follower_count", "count_source", "last_synced_at")
    readonly_fields = ("ownership", "count_source", "last_synced_at")


@admin.register(CreatorProfile)
class CreatorProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "headline", "verification_status", "verified_reach", "status")
    list_filter = ("verification_status", "status", "categories")
    search_fields = ("user__handle", "user__display_name", "headline")
    raw_id_fields = ("user",)
    # Verification changes go through the review workflow (audited), not the admin.
    readonly_fields = ("verification_status", "verified_at", "verified_reach")
    inlines = (LinkedAccountInline,)


@admin.register(VerificationRequest)
class VerificationRequestAdmin(admin.ModelAdmin):
    list_display = ("profile", "status", "created_at", "reviewed_by", "reviewed_at")
    list_filter = ("status",)
    raw_id_fields = ("profile", "reviewed_by")
    readonly_fields = ("status", "reviewed_by", "reviewed_at", "decision_reason")

    def has_add_permission(self, request: Any) -> bool:
        return False


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = ("title", "brand_name", "status", "visibility", "accepted_count", "slots", "hidden_at")
    list_filter = ("status", "visibility")
    search_fields = ("title", "brand_name")
    raw_id_fields = ("owner",)
    readonly_fields = ("accepted_count", "published_at", "closed_at", "hidden_at", "hidden_reason")

    def get_queryset(self, request: Any) -> Any:
        return Campaign.all_objects.all()
