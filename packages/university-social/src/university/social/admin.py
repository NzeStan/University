from __future__ import annotations

from typing import Any

from django.contrib import admin, messages

from university.core.exceptions import UniversityError
from university.social import services
from university.social.models import Comment, Hashtag, Post, PostMedia, PostRevision, SocialProfile


class RevisionInline(admin.TabularInline):
    model = PostRevision
    extra = 0
    readonly_fields = ("body", "created_at")
    can_delete = False


class MediaInline(admin.TabularInline):
    model = PostMedia
    extra = 0
    fields = ("file", "mime_type", "alt_text", "position")
    readonly_fields = fields


@admin.register(Post)
class PostAdmin(admin.ModelAdmin):
    """Moderation goes through audited services (actions below)."""

    list_display = ("id", "author", "visibility", "status", "reaction_count", "comment_count", "created_at")
    list_filter = ("status", "visibility")
    search_fields = ("body", "author__handle")
    raw_id_fields = ("author", "repost_of")
    readonly_fields = ("status", "moderation_reason", "reaction_count", "comment_count", "repost_count", "edited_at")
    inlines = (MediaInline, RevisionInline)
    actions = ["hide_selected", "restore_selected"]

    def get_queryset(self, request: Any) -> Any:
        return Post.all_objects.select_related("author")

    def _run(self, request: Any, queryset: Any, func: Any) -> None:
        for post in queryset:
            try:
                func(actor=request.user, post_id=post.pk, reason="Moderated in admin")
            except UniversityError as exc:
                self.message_user(request, f"{post.pk}: {exc.message}", messages.ERROR)

    @admin.action(description="Hide selected posts")
    def hide_selected(self, request: Any, queryset: Any) -> None:
        self._run(request, queryset, services.hide_post)

    @admin.action(description="Restore / approve selected posts")
    def restore_selected(self, request: Any, queryset: Any) -> None:
        self._run(request, queryset, services.restore_post)


@admin.register(Comment)
class CommentAdmin(admin.ModelAdmin):
    list_display = ("id", "author", "post", "status", "created_at")
    list_filter = ("status",)
    search_fields = ("body", "author__handle")
    raw_id_fields = ("author", "post", "parent")
    readonly_fields = ("status", "moderation_reason")


@admin.register(Hashtag)
class HashtagAdmin(admin.ModelAdmin):
    list_display = ("name", "posts_count")
    search_fields = ("name",)


@admin.register(SocialProfile)
class SocialProfileAdmin(admin.ModelAdmin):
    list_display = ("user", "followers_count", "following_count", "posts_count", "requires_follow_approval")
    raw_id_fields = ("user",)
    readonly_fields = ("followers_count", "following_count", "posts_count")
