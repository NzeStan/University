from django.contrib import admin

from university.__module__.models import Item


@admin.register(Item)
class ItemAdmin(admin.ModelAdmin):
    list_display = ("title", "owner", "created_at", "deleted_at")
    raw_id_fields = ("owner",)
