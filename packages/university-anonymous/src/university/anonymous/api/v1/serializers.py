"""Anonymous API serializers.

Every author representation is the literal ``{"anonymous": true}`` (plus a
per-thread pseudonym for comments). ``viewer.is_author`` is computed for the
requesting user only, from owner tokens, and is the one place authorship is
acknowledged — to the author themselves.
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.anonymous.conf import anonymous_settings
from university.users.refs import PersonRefSerializer

ANONYMOUS_AUTHOR = {"anonymous": True}


class AnonymousAuthorSerializer(serializers.Serializer):
    anonymous = serializers.BooleanField()


class AnonymousCommentAuthorSerializer(AnonymousAuthorSerializer):
    pseudonym = serializers.CharField(help_text="Stable within one thread, unlinkable across threads.")
    is_op = serializers.BooleanField()


class AnonymousAudienceSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class AnonymousCountsSerializer(serializers.Serializer):
    reactions = serializers.IntegerField()
    comments = serializers.IntegerField()


class AnonymousPostViewerSerializer(serializers.Serializer):
    reaction = serializers.CharField(allow_null=True)
    is_author = serializers.BooleanField()


class AnonymousCommentViewerSerializer(serializers.Serializer):
    is_author = serializers.BooleanField()


class AnonymousPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)


class AnonymousPostSerializer(serializers.Serializer):
    """Declared fields document the schema; ``status``/``moderation_reason`` appear for the author only."""

    id = serializers.UUIDField(read_only=True)
    author = AnonymousAuthorSerializer(read_only=True)
    body = serializers.CharField(read_only=True)
    visibility = serializers.CharField(read_only=True)
    audience = AnonymousAudienceSerializer(read_only=True, allow_null=True)
    comments_enabled = serializers.BooleanField(read_only=True)
    counts = AnonymousCountsSerializer(read_only=True)
    viewer = AnonymousPostViewerSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)
    status = serializers.CharField(required=False, help_text="Only for the author.")
    moderation_reason = serializers.CharField(allow_null=True, required=False, help_text="Only for the author.")

    def to_representation(self, post: Any) -> dict[str, Any]:
        authored = self.context.get("authored", set())
        is_author = str(post.pk) in authored
        data = {
            "id": str(post.pk),
            "author": ANONYMOUS_AUTHOR,
            "body": post.body,
            "visibility": post.visibility,
            "audience": {"type": post.scope_type, "id": post.scope_id} if post.scope_type else None,
            "comments_enabled": post.comments_enabled,
            "counts": {"reactions": post.reaction_count, "comments": post.comment_count},
            "viewer": {"reaction": getattr(post, "viewer_reaction", None), "is_author": is_author},
            "created_at": post.created_at.isoformat(),
        }
        if is_author:
            data["status"] = post.status
            data["moderation_reason"] = post.moderation_reason or None
        return data


class AnonymousCommentSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    post = serializers.UUIDField(read_only=True)
    author = AnonymousCommentAuthorSerializer(read_only=True)
    body = serializers.CharField(read_only=True)
    viewer = AnonymousCommentViewerSerializer(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, comment: Any) -> dict[str, Any]:
        authored = self.context.get("authored", set())
        return {
            "id": str(comment.pk),
            "post": str(comment.post_id),
            "author": {**ANONYMOUS_AUTHOR, "pseudonym": comment.pseudonym, "is_op": comment.is_op},
            "body": comment.body,
            "viewer": {"is_author": str(comment.pk) in authored},
            "created_at": comment.created_at.isoformat(),
        }


class AnonymousPostCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)
    visibility = serializers.CharField(max_length=16)
    audience_id = serializers.CharField(max_length=64, required=False)
    comments_enabled = serializers.BooleanField(default=True)


class AnonymousCommentCreateSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)


class AnonymousReactionSerializer(serializers.Serializer):
    kind = serializers.CharField(max_length=16, default="like")

    def validate_kind(self, value: str) -> str:
        if value not in anonymous_settings.get("REACTION_TYPES", []):
            raise serializers.ValidationError("Unknown reaction.")
        return value


class AnonymousRevealRequestCreateSerializer(serializers.Serializer):
    kind = serializers.ChoiceField(choices=["post", "comment", "message"])
    object_id = serializers.UUIDField()
    justification = serializers.CharField(max_length=4000)
    case_reference = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")


class AnonymousRevealDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=500)


class AnonymousRevealRequestSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    kind = serializers.CharField(read_only=True, help_text="post or comment")
    object_id = serializers.UUIDField(read_only=True)
    justification = serializers.CharField(read_only=True)
    case_reference = serializers.CharField(read_only=True, allow_null=True)
    status = serializers.CharField(read_only=True)
    requester = AnonymousPersonSerializer(read_only=True)
    approver = AnonymousPersonSerializer(read_only=True, allow_null=True)
    decision_reason = serializers.CharField(read_only=True, allow_null=True)
    expires_at = serializers.DateTimeField(read_only=True, allow_null=True)
    retrieval_count = serializers.IntegerField(read_only=True)
    created_at = serializers.DateTimeField(read_only=True)

    def to_representation(self, request: Any) -> dict[str, Any]:
        return {
            "id": str(request.pk),
            "kind": request.kind,
            "object_id": str(request.object_id),
            "justification": request.justification,
            "case_reference": request.case_reference or None,
            "status": request.status,
            "requester": {"id": str(request.requester_id), "handle": request.requester.handle},
            "approver": {"id": str(request.approver_id), "handle": request.approver.handle}
            if request.approver_id
            else None,
            "decision_reason": request.decision_reason or None,
            "expires_at": request.expires_at.isoformat() if request.expires_at else None,
            "retrieval_count": request.retrieval_count,
            "created_at": request.created_at.isoformat(),
        }


class AnonymousRevealedIdentitySerializer(serializers.Serializer):
    """Returned only to an approved requester, never cached, and every retrieval is audited."""

    user_id = serializers.UUIDField()
    email = serializers.EmailField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()
    status = serializers.CharField()


# ------------------------------------------------------------------ anonymous inbox
class AnonymousInboxSerializer(serializers.Serializer):
    """Your own inbox settings."""

    enabled = serializers.BooleanField()
    prompt = serializers.CharField(max_length=200, allow_blank=True)
    unread_count = serializers.IntegerField(read_only=True)
    blocked_senders = serializers.IntegerField(read_only=True)


class AnonymousInboxUpdateSerializer(serializers.Serializer):
    enabled = serializers.BooleanField(required=False)
    prompt = serializers.CharField(max_length=200, allow_blank=True, required=False)


class AnonymousPublicInboxSerializer(serializers.Serializer):
    owner = PersonRefSerializer()
    prompt = serializers.CharField()
    answers_count = serializers.IntegerField()


class AnonymousMessageSendSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)


class AnonymousInboxMessageSerializer(serializers.Serializer):
    """A message in your inbox. There is no sender field, by design."""

    id = serializers.UUIDField()
    body = serializers.CharField()
    status = serializers.CharField()
    read_at = serializers.DateTimeField(allow_null=True)
    answer = serializers.CharField(allow_blank=True)
    answer_public = serializers.BooleanField()
    answered_at = serializers.DateTimeField(allow_null=True)
    created_at = serializers.DateTimeField()


class AnonymousAnswerSerializer(serializers.Serializer):
    answer = serializers.CharField(max_length=20000)
    public = serializers.BooleanField(default=False, help_text="Show the question and answer on your profile.")


class AnonymousPublicAnswerSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    question = serializers.CharField(source="body")
    answer = serializers.CharField()
    answered_at = serializers.DateTimeField()
