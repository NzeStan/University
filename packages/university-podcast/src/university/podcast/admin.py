from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.podcast.models import Episode, Podcast, PodcastMember


class MemberInline(admin.TabularInline):
    model = PodcastMember
    extra = 0
    raw_id_fields = ("user",)


@admin.register(Podcast)
class PodcastAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "visibility", "subscriber_count", "hidden_at")
    list_filter = ("status", "visibility", "category", "language")
    search_fields = ("title", "slug")
    raw_id_fields = ("owner",)
    readonly_fields = ("subscriber_count", "hidden_at", "hidden_reason")
    inlines = (MemberInline,)

    def get_queryset(self, request: Any) -> Any:
        return Podcast.all_objects.all()


@admin.register(Episode)
class EpisodeAdmin(admin.ModelAdmin):
    list_display = ("title", "podcast", "status", "published_at", "hidden_at")
    list_filter = ("status", "episode_type")
    search_fields = ("title",)
    raw_id_fields = ("podcast", "season", "created_by")
    readonly_fields = ("hidden_at", "hidden_reason", "duration_seconds")
