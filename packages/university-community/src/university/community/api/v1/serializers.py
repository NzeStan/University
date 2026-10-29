from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.community.constants import CommentingPolicy, PostingPolicy, Privacy, Role
from university.community.models import Community, CommunityMembership
from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.users.refs import PersonRefSerializer, person_ref


class CommunitySerializer(StrictModelSerializer):
    parent = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta:
        model = Community
        fields = (
            "id",
            "name",
            "slug",
            "description",
            "rules",
            "kind",
            "privacy",
            "status",
            "parent",
            "requires_scope_membership",
            "is_official",
            "posting_policy",
            "commenting_policy",
            "member_count",
            "viewer",
            "created_at",
        )
        read_only_fields = fields

    def get_parent(self, obj: Community) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None

    def get_viewer(self, obj: Community) -> dict[str, Any]:
        memberships = self.context.get("memberships", {})
        member = memberships.get(obj.pk)
        return {"role": member.role, "status": member.status} if member else {"role": None, "status": None}


class CommunityCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120)
    slug = serializers.SlugField(max_length=90, required=False)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True, default="")
    rules = serializers.ListField(child=serializers.CharField(max_length=500), required=False, max_length=30)
    kind = serializers.CharField(max_length=32, default="interest")
    privacy = serializers.ChoiceField(choices=Privacy.choices, default=Privacy.PUBLIC)
    parent_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="")
    parent_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="")
    requires_scope_membership = serializers.BooleanField(default=False)
    posting_policy = serializers.ChoiceField(choices=PostingPolicy.choices, default=PostingPolicy.MEMBERS)
    commenting_policy = serializers.ChoiceField(choices=CommentingPolicy.choices, default=CommentingPolicy.MEMBERS)
    official = serializers.BooleanField(default=False)


class CommunityUpdateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=120, required=False)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    rules = serializers.ListField(child=serializers.CharField(max_length=500), required=False, max_length=30)
    kind = serializers.CharField(max_length=32, required=False)
    privacy = serializers.ChoiceField(choices=Privacy.choices, required=False)
    requires_scope_membership = serializers.BooleanField(required=False)
    posting_policy = serializers.ChoiceField(choices=PostingPolicy.choices, required=False)
    commenting_policy = serializers.ChoiceField(choices=CommentingPolicy.choices, required=False)


class CommunityMemberSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = CommunityMembership
        fields = ("user", "role", "status", "joined_at")
        read_only_fields = fields

    @extend_schema_field(PersonRefSerializer)
    def get_user(self, obj: CommunityMembership) -> dict[str, Any] | None:
        return person_ref(obj.user)


class CommunityMembershipSerializer(StrictModelSerializer):
    community = CommunitySerializer(read_only=True)

    class Meta:
        model = CommunityMembership
        fields = ("community", "role", "status", "joined_at")
        read_only_fields = fields


class CommunityRoleSerializer(serializers.Serializer):
    role = serializers.ChoiceField(choices=[r for r in Role.values if r != Role.OWNER])


class CommunityReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")


class CommunityUserRefSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


class CommunityInviteLinkCreateSerializer(serializers.Serializer):
    expires_in_hours = serializers.IntegerField(default=168, min_value=1)
    max_uses = serializers.IntegerField(required=False, allow_null=True, min_value=1)


class CommunityJoinCodeSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=128)


class CommunityOfficialSerializer(serializers.Serializer):
    official = serializers.BooleanField()


class CommunityInviteLinkSerializer(serializers.Serializer):
    """A new invite link. ``code`` is shown only once; only its hash is stored."""

    id = serializers.UUIDField()
    code = serializers.CharField()
    expires_at = serializers.DateTimeField()
    max_uses = serializers.IntegerField(allow_null=True)
