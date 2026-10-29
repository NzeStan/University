from django.contrib import admin

from university.messaging.models import Conversation


@admin.register(Conversation)
class ConversationAdmin(admin.ModelAdmin):
    """Metadata only: message text is private and never shown in the admin."""

    list_display = ("id", "kind", "last_message_at", "created_at")
    list_filter = ("kind",)
    readonly_fields = ("kind", "title", "created_by", "direct_key", "last_message_at")
