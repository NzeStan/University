from django.contrib import admin

from university.promotions.models import Campaign


@admin.register(Campaign)
class CampaignAdmin(admin.ModelAdmin):
    list_display = (
        "name",
        "kind",
        "status",
        "budget_minor",
        "currency",
        "impressions",
        "clicks",
        "starts_at",
        "ends_at",
    )
    list_filter = ("kind", "status")
    search_fields = ("name", "headline")
    readonly_fields = ("advertiser", "impressions", "clicks", "payment_reference", "reviewed_by", "reviewed_at")
