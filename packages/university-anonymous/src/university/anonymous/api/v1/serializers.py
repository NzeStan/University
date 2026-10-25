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

ANONYMOUS_AUTHOR = {"anonymous": True}


class AnonymousPostSerializer(serializers.Serializer):
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
    kind = serializers.ChoiceField(choices=["post", "comment"])
    object_id = serializers.UUIDField()
    justification = serializers.CharField(max_length=4000)
    case_reference = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")


class AnonymousRevealDecisionSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    reason = serializers.CharField(max_length=500)


class AnonymousRevealRequestSerializer(serializers.Serializer):
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
