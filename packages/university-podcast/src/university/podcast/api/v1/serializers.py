from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.podcast.constants import EpisodeType, MemberRole, ShowVisibility, TranscriptFormat
from university.podcast.models import Clip, Episode, EpisodeGuest, Podcast, PodcastMember, Season, Transcript


class PodcastPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()


def person(user: Any) -> dict[str, Any] | None:
    if user is None or not user.is_active:
        return None
    return {"id": user.pk, "handle": user.handle, "display_name": user.display_name or user.handle or ""}


class PodcastScopeRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class PodcastShowSerializer(StrictModelSerializer):
    host = serializers.SerializerMethodField()
    has_cover = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta:
        model = Podcast
        fields = (
            "id",
            "slug",
            "title",
            "description",
            "author_name",
            "category",
            "language",
            "explicit",
            "website",
            "visibility",
            "status",
            "host",
            "has_cover",
            "subscriber_count",
            "published_at",
            "viewer",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(PodcastScopeRefSerializer(allow_null=True))
    def get_host(self, obj: Podcast) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None

    def get_has_cover(self, obj: Podcast) -> bool:
        return bool(obj.cover_media_id)

    @extend_schema_field(serializers.DictField())
    def get_viewer(self, obj: Podcast) -> dict[str, Any]:
        return {
            "subscribed": obj.pk in (self.context.get("subscribed") or set()),
            "role": (self.context.get("roles") or {}).get(obj.pk),
        }


class PodcastShowWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=10000, required=False, allow_blank=True)
    author_name = serializers.CharField(max_length=120, required=False, allow_blank=True)
    category = serializers.CharField(max_length=40, required=False)
    language = serializers.CharField(max_length=8, required=False)
    explicit = serializers.BooleanField(required=False)
    website = serializers.URLField(max_length=300, required=False, allow_blank=True)
    visibility = serializers.ChoiceField(choices=ShowVisibility.choices, required=False)
    cover_media_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    host_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)
    host_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="", write_only=True)


class PodcastActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["publish", "archive"])


class PodcastMemberSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = PodcastMember
        fields = ("user", "role", "created_at")
        read_only_fields = fields

    @extend_schema_field(PodcastPersonSerializer(allow_null=True))
    def get_user(self, obj: PodcastMember) -> dict[str, Any] | None:
        return person(obj.user)


class PodcastMemberWriteSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=[MemberRole.HOST, MemberRole.PRODUCER])


class PodcastUserRefSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


class PodcastSeasonSerializer(StrictModelSerializer):
    class Meta:
        model = Season
        fields = ("id", "number", "title", "description")
        read_only_fields = fields


class PodcastSeasonWriteSerializer(serializers.Serializer):
    number = serializers.IntegerField(min_value=1, max_value=1000)
    title = serializers.CharField(max_length=160, required=False, allow_blank=True, default="")
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")


class PodcastGuestSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = EpisodeGuest
        fields = ("id", "name", "bio", "user")
        read_only_fields = fields

    @extend_schema_field(PodcastPersonSerializer(allow_null=True))
    def get_user(self, obj: EpisodeGuest) -> dict[str, Any] | None:
        """Linked accounts appear only after the guest confirms."""
        return person(obj.user) if obj.confirmed_at else None


class PodcastGuestWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    bio = serializers.CharField(max_length=300, required=False, allow_blank=True, default="")
    user_id = serializers.UUIDField(required=False, allow_null=True)


class PodcastEpisodeSerializer(StrictModelSerializer):
    season = serializers.SerializerMethodField()
    guests = serializers.SerializerMethodField()
    has_audio = serializers.SerializerMethodField()
    has_video = serializers.SerializerMethodField()
    has_transcript = serializers.SerializerMethodField()

    class Meta:
        model = Episode
        fields = (
            "id",
            "podcast",
            "slug",
            "title",
            "summary",
            "show_notes",
            "episode_type",
            "number",
            "season",
            "explicit",
            "duration_seconds",
            "has_audio",
            "has_video",
            "has_transcript",
            "guests",
            "status",
            "publish_at",
            "published_at",
            "created_at",
        )
        read_only_fields = fields

    def get_season(self, obj: Episode) -> int | None:
        return obj.season.number if obj.season_id else None

    @extend_schema_field(PodcastGuestSerializer(many=True))
    def get_guests(self, obj: Episode) -> list[dict[str, Any]]:
        return PodcastGuestSerializer(obj.guests.all(), many=True).data

    def get_has_audio(self, obj: Episode) -> bool:
        return bool(obj.audio_media_id)

    def get_has_video(self, obj: Episode) -> bool:
        return bool(obj.video_media_id)

    def get_has_transcript(self, obj: Episode) -> bool:
        return Transcript.objects.filter(episode=obj, status="ready").exists()


class PodcastEpisodeWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=200)
    summary = serializers.CharField(max_length=500, required=False, allow_blank=True)
    show_notes = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    episode_type = serializers.ChoiceField(choices=EpisodeType.choices, required=False)
    explicit = serializers.BooleanField(required=False)
    number = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    season = serializers.UUIDField(required=False, allow_null=True)
    audio_media_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    video_media_id = serializers.CharField(max_length=64, required=False, allow_blank=True)


class PodcastPublishSerializer(serializers.Serializer):
    publish_at = serializers.DateTimeField(required=False, allow_null=True)


class PodcastTranscriptSerializer(StrictModelSerializer):
    class Meta:
        model = Transcript
        fields = ("language", "source_format", "text", "cues", "status", "automatic", "error", "updated_at")
        read_only_fields = fields


class PodcastTranscriptWriteSerializer(serializers.Serializer):
    content = serializers.CharField(max_length=2_500_000, trim_whitespace=False)
    format = serializers.ChoiceField(choices=TranscriptFormat.choices, default=TranscriptFormat.VTT)
    language = serializers.CharField(max_length=8, default="en")


class PodcastLanguageSerializer(serializers.Serializer):
    language = serializers.CharField(max_length=8, default="en")


class PodcastClipSerializer(StrictModelSerializer):
    class Meta:
        model = Clip
        fields = ("id", "title", "start_seconds", "end_seconds", "created_at")
        read_only_fields = fields


class PodcastClipWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    start_seconds = serializers.FloatField(min_value=0)
    end_seconds = serializers.FloatField(min_value=0)


class PodcastPlaySerializer(serializers.Serializer):
    position_seconds = serializers.FloatField(min_value=0, default=0)


class PodcastPlayResultSerializer(serializers.Serializer):
    play = serializers.BooleanField()
    completion = serializers.BooleanField()


class PodcastGuestResponseSerializer(serializers.Serializer):
    accept = serializers.BooleanField()
