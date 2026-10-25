from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.media.models import MediaAsset


@admin.register(MediaAsset)
class MediaAssetAdmin(admin.ModelAdmin):
    list_display = ("id", "kind", "status", "mime_type", "size", "owner", "created_at")
    list_filter = ("kind", "status")
    raw_id_fields = ("owner", "source")
    # Files are private and served only through signed links.
    exclude = ("file",)
    readonly_fields = ("mime_type", "size", "sha256", "duration_seconds", "width", "height", "error", "processed_at")

    def has_add_permission(self, request: Any) -> bool:
        return False
