from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.community.models import Community, CommunityMembership


class MembershipInline(admin.TabularInline):
    model = CommunityMembership
    extra = 0
    raw_id_fields = ("user", "invited_by")
    fields = ("user", "role", "status", "joined_at")
    readonly_fields = ("joined_at",)


@admin.register(Community)
class CommunityAdmin(admin.ModelAdmin):
    list_display = ("name", "slug", "kind", "privacy", "status", "is_official", "member_count", "created_at")
    list_filter = ("kind", "privacy", "status", "is_official")
    search_fields = ("name", "slug", "description")
    readonly_fields = ("member_count", "created_by")
    inlines = (MembershipInline,)

    def get_queryset(self, request: Any) -> Any:
        return Community.all_objects.all()
