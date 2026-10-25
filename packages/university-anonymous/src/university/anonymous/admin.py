"""Admin for anonymous content.

Authorship and reveal records are intentionally NOT registered: the only way
to an identity is the audited, two-person reveal API.
"""

from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.anonymous.models import AnonymousComment, AnonymousPost


class ContentAdmin(admin.ModelAdmin):
    list_filter = ("status",)
    search_fields = ("body",)
    readonly_fields = ("status", "moderation_reason")

    def has_add_permission(self, request: Any) -> bool:
        return False

    def has_change_permission(self, request: Any, obj: Any = None) -> bool:
        return False


@admin.register(AnonymousPost)
class AnonymousPostAdmin(ContentAdmin):
    list_display = ("id", "visibility", "scope_type", "status", "reaction_count", "comment_count", "created_at")


@admin.register(AnonymousComment)
class AnonymousCommentAdmin(ContentAdmin):
    list_display = ("id", "post", "pseudonym", "status", "created_at")
    exclude = ("thread_token",)
