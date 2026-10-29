from django.contrib import admin

from university.opportunities.models import Application, Opportunity


@admin.register(Opportunity)
class OpportunityAdmin(admin.ModelAdmin):
    list_display = ("title", "organization_name", "kind", "status", "is_hidden", "verified_at", "published_at")
    list_filter = ("kind", "status", "is_hidden")
    search_fields = ("title", "organization_name")
    readonly_fields = ("poster", "applications_count", "published_at", "closed_at", "verified_by")


@admin.register(Application)
class ApplicationAdmin(admin.ModelAdmin):
    list_display = ("opportunity", "status", "created_at")
    list_filter = ("status",)
    readonly_fields = ("opportunity", "applicant", "cover_note", "contact_email", "resume", "created_at")
    exclude = ()
