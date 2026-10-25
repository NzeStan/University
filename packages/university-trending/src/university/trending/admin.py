from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.trending.models import TrendingScore


@admin.register(TrendingScore)
class TrendingScoreAdmin(admin.ModelAdmin):
    list_display = ("content_type", "object_id", "score", "scope_type", "computed_at")
    list_filter = ("content_type", "scope_type")

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False
