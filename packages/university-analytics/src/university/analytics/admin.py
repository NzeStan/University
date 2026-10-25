from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.analytics.models import MetricDaily


@admin.register(MetricDaily)
class MetricDailyAdmin(admin.ModelAdmin):
    list_display = ("date", "metric", "scope_type", "scope_id", "count")
    list_filter = ("metric", "scope_type")
    date_hierarchy = "date"

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False
