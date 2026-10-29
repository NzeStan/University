"""Social API serializers.

Representations never expose another user's email, phone or internal state.
``status`` and ``moderation_reason`` are only shown to the author.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.utils import timezone
from rest_framework import serializers

from university.core.api.serializers import StrictModelSerializer
from university.social.conf import social_settings
from university.social.constants import ContentStatus, Visibility
from university.social.models import Comment, Follow, PostMedia, SocialProfile
from university.users.services.avatars import avatar_url


class UserSummarySerializer(StrictModelSerializer):
    avatar_url = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ("id", "handle", "display_name", "avatar_url")
        read_only_fields = fields

    def get_avatar_url(self, obj: Any) -> str | None:
        return avatar_url(obj)


class MediaSerializer(StrictModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = PostMedia
        fields = ("id", "url", "mime_type", "size", "width", "height", "alt_text")
        read_only_fields = fields

    def get_url(self, obj: PostMedia) -> str:
        url = obj.file.url
        request = self.context.get("request")
        return request.build_absolute_uri(url) if request is not None and url.startswith("/") else url


class MediaUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    alt_text = serializers.CharField(max_length=500, required=False, allow_blank=True)


def _viewer(context: dict[str, Any]) -> Any:
    request = context.get("request")
    return getattr(request, "user", None)


def poll_representation(post: Any, context: dict[str, Any]) -> dict[str, Any] | None:
    poll = getattr(post, "poll", None) if hasattr(post, "poll") else None
    if poll is None:
        return None
    voted = context.get("poll_votes", {}).get(poll.pk, set())
    return {
        "id": str(poll.pk),
        "allows_multiple": poll.allows_multiple,
        "closes_at": poll.closes_at.isoformat() if poll.closes_at else None,
        "closed": bool(poll.closes_at and poll.closes_at <= timezone.now()),
        "total_votes": poll.total_votes,
        "options": [
            {"id": str(o.pk), "text": o.text, "vote_count": o.vote_count, "voted": o.pk in voted}
            for o in poll.options.all()
        ],
    }


class SocialAudienceSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class SocialMentionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)


class SocialPollOptionSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    text = serializers.CharField()
    vote_count = serializers.IntegerField()
    voted = serializers.BooleanField()


class SocialPollSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    allows_multiple = serializers.BooleanField()
    closes_at = serializers.DateTimeField(allow_null=True)
    closed = serializers.BooleanField()
    total_votes = serializers.IntegerField()
    options = SocialPollOptionSerializer(many=True)


class SocialRepostOfSerializer(serializers.Serializer):
    """The original of a repost: just its id and ``unavailable: true`` when the viewer can't see it."""

    id = serializers.UUIDField()
    unavailable = serializers.BooleanField()
    author = UserSummarySerializer(required=False)
    body = serializers.CharField(required=False)
    created_at = serializers.DateTimeField(required=False)


class SocialPostCountsSerializer(serializers.Serializer):
    reactions = serializers.IntegerField()
    comments = serializers.IntegerField()
    reposts = serializers.IntegerField()


class SocialPostViewerSerializer(serializers.Serializer):
    reaction = serializers.CharField(allow_null=True)
    bookmarked = serializers.BooleanField()
    reposted = serializers.BooleanField()
    is_author = serializers.BooleanField()


class PostSerializer(serializers.Serializer):
    """Read representation of a post (built from selector-annotated querysets).

    The declared fields document the shape for the API schema; ``to_representation`` builds it.
    ``status`` and ``moderation_reason`` appear only for the author.
    """

    id = serializers.UUIDField(read_only=True)
    author = UserSummarySerializer(read_only=True)
    body = serializers.CharField(read_only=True)
    visibility = serializers.ChoiceField(choices=Visibility.choices, read_only=True)
    audience = SocialAudienceSerializer(read_only=True, allow_null=True)
    hashtags = serializers.ListField(child=serializers.CharField(), read_only=True)
    mentions = SocialMentionSerializer(many=True, read_only=True)
    links = serializers.ListField(child=serializers.CharField(), read_only=True)
    media = MediaSerializer(many=True, read_only=True)
    poll = SocialPollSerializer(read_only=True, allow_null=True)
    repost_of = SocialRepostOfSerializer(read_only=True, allow_null=True)
    is_repost = serializers.BooleanField(read_only=True)
    location = serializers.CharField(read_only=True, allow_null=True)
    comments_enabled = serializers.BooleanField(read_only=True)
    counts = SocialPostCountsSerializer(read_only=True)
    viewer = SocialPostViewerSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    edited_at = serializers.DateTimeField(read_only=True, allow_null=True)
    status = serializers.ChoiceField(choices=ContentStatus.choices, required=False, help_text="Only for the author.")
    moderation_reason = serializers.CharField(allow_null=True, required=False, help_text="Only for the author.")

    def to_representation(self, post: Any) -> dict[str, Any]:
        viewer = _viewer(self.context)
        is_author = bool(viewer and viewer.is_authenticated and viewer.pk == post.author_id)
        data: dict[str, Any] = {
            "id": str(post.pk),
            "author": UserSummarySerializer(post.author).data,
            "body": post.body,
            "visibility": post.visibility,
            "audience": {"type": post.scope_type, "id": post.scope_id} if post.scope_type else None,
            "hashtags": [h.name for h in post.hashtags.all()],
            "mentions": [{"id": str(m.user_id), "handle": m.user.handle} for m in post.mentions.all()],
            "links": post.links,
            "media": MediaSerializer(post.media.all(), many=True, context=self.context).data,
            "poll": poll_representation(post, self.context),
            "repost_of": self._original(post),
            "is_repost": post.is_pure_repost,
            "location": post.location or None,
            "comments_enabled": post.comments_enabled,
            "counts": {
                "reactions": post.reaction_count,
                "comments": post.comment_count,
                "reposts": post.repost_count,
            },
            "viewer": {
                "reaction": getattr(post, "viewer_reaction", None),
                "bookmarked": bool(getattr(post, "viewer_bookmarked", False)),
                "reposted": bool(getattr(post, "viewer_reposted", False)),
                "is_author": is_author,
            },
            "created_at": post.created_at.isoformat(),
            "edited_at": post.edited_at.isoformat() if post.edited_at else None,
        }
        if is_author:
            data["status"] = post.status
            data["moderation_reason"] = post.moderation_reason or None
        return data

    def _original(self, post: Any) -> dict[str, Any] | None:
        if not post.repost_of_id:
            return None
        original = post.repost_of
        if original is None or original.pk not in self.context.get("visible_originals", set()):
            return {"id": str(post.repost_of_id), "unavailable": True}
        return {
            "id": str(original.pk),
            "author": UserSummarySerializer(original.author).data,
            "body": original.body,
            "created_at": original.created_at.isoformat(),
            "unavailable": False,
        }


class PollCreateSerializer(serializers.Serializer):
    options = serializers.ListField(child=serializers.CharField(max_length=100), min_length=2, max_length=10)
    allows_multiple = serializers.BooleanField(default=False)
    duration_hours = serializers.IntegerField(required=False, min_value=1)


class PostCreateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, trim_whitespace=False, max_length=20000)
    visibility = serializers.ChoiceField(choices=Visibility.choices, required=False)
    audience_id = serializers.CharField(required=False, max_length=64, help_text="Scope id for audience visibilities.")
    media = serializers.ListField(child=serializers.UUIDField(), required=False, max_length=20)
    poll = PollCreateSerializer(required=False)
    location = serializers.CharField(required=False, allow_blank=True, max_length=100)
    comments_enabled = serializers.BooleanField(default=True)


class PostUpdateSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, max_length=20000)
    comments_enabled = serializers.BooleanField(required=False)


class RepostSerializer(serializers.Serializer):
    body = serializers.CharField(required=False, allow_blank=True, default="", max_length=20000)


class ReactionSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=16, default="like")

    def validate_kind(self, value: str) -> str:
        if value not in social_settings.get("REACTION_TYPES", []):
            raise serializers.ValidationError("Unknown reaction.")
        return value


class PollVoteSerializer(serializers.Serializer):
    options = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=10)


class CommentSerializer(StrictModelSerializer):
    author = UserSummarySerializer(read_only=True)
    post = serializers.UUIDField(source="post_id", read_only=True)
    parent = serializers.UUIDField(source="parent_id", read_only=True, allow_null=True)
    viewer_reaction = serializers.SerializerMethodField()

    class Meta:
        model = Comment
        fields = (
            "id",
            "post",
            "parent",
            "author",
            "body",
            "reaction_count",
            "reply_count",
            "viewer_reaction",
            "created_at",
            "edited_at",
        )
        read_only_fields = fields

    def get_viewer_reaction(self, obj: Comment) -> str | None:
        return getattr(obj, "viewer_reaction", None)


class CommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)
    parent = serializers.UUIDField(required=False, allow_null=True)


class CommentUpdateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)


class SocialProfileSerializer(StrictModelSerializer):
    class Meta:
        model = SocialProfile
        fields = (
            "bio",
            "website",
            "requires_follow_approval",
            "allow_mentions_from",
            "default_post_visibility",
            "followers_count",
            "following_count",
            "posts_count",
        )
        read_only_fields = ("followers_count", "following_count", "posts_count")


class FollowSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = Follow
        fields = ("id", "user", "status", "created_at")
        read_only_fields = fields

    def get_user(self, obj: Follow) -> dict[str, Any]:
        side = self.context.get("side", "follower")
        return UserSummarySerializer(getattr(obj, side)).data


class ModerationSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class FollowResultSerializer(serializers.Serializer):
    status = serializers.CharField()


class HashtagSerializer(serializers.Serializer):
    name = serializers.CharField()
    posts_count = serializers.IntegerField()


class SocialFeedPageSerializer(serializers.Serializer):
    """A page of a feed: cursor feeds send ``next``/``previous``; ranked feeds send ``offset``/``limit``."""

    next = serializers.URLField(allow_null=True, required=False)
    previous = serializers.URLField(allow_null=True, required=False)
    offset = serializers.IntegerField(required=False)
    limit = serializers.IntegerField(required=False)
    results = PostSerializer(many=True)
