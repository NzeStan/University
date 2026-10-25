from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.search.models import SearchEntry


@admin.register(SearchEntry)
class SearchEntryAdmin(admin.ModelAdmin):
    list_display = ("index", "object_id", "title", "tags", "updated_at")
    list_filter = ("index",)
    search_fields = ("title",)

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False
