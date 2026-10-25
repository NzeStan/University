from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.creator.constants import CampaignVisibility, KitVisibility, ProfileStatus
from university.creator.models import (
    Campaign,
    CreatorCategory,
    CreatorProfile,
    Deliverable,
    LinkedAccount,
    MediaKit,
    Participation,
    VerificationRequest,
)
from university.creator.providers import providers


class CreatorPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()


def person(user: Any) -> dict[str, Any] | None:
    if user is None or not user.is_active:
        return None
    return {"id": user.pk, "handle": user.handle, "display_name": user.display_name or user.handle or ""}


class CreatorCategorySerializer(StrictModelSerializer):
    class Meta:
        model = CreatorCategory
        fields = ("key", "name")
        read_only_fields = fields


class CreatorProviderSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    automatic_verification = serializers.BooleanField()


def provider_list() -> list[dict[str, Any]]:
    return [
        {"key": key, "label": p.label, "automatic_verification": p.supports_lookup} for key, p in providers().items()
    ]


# ---------------------------------------------------------------- accounts
class CreatorLinkedAccountSerializer(StrictModelSerializer):
    """Public view of a linked account."""

    class Meta:
        model = LinkedAccount
        fields = ("id", "provider", "handle", "url", "display_name", "follower_count", "count_source", "ownership")
        read_only_fields = fields


class CreatorOwnLinkedAccountSerializer(CreatorLinkedAccountSerializer):
    """The owner's view: includes the challenge code to place in their bio."""

    class Meta(CreatorLinkedAccountSerializer.Meta):
        fields = (
            *CreatorLinkedAccountSerializer.Meta.fields,
            "challenge",
            "is_public",
            "verified_at",
            "last_synced_at",
        )
        read_only_fields = fields


class CreatorLinkAccountSerializer(serializers.Serializer):
    provider = serializers.CharField(max_length=32)
    handle = serializers.CharField(max_length=100)
    follower_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class CreatorAccountUpdateSerializer(serializers.Serializer):
    follower_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    is_public = serializers.BooleanField(required=False, allow_null=True)


class CreatorConfirmAccountSerializer(serializers.Serializer):
    follower_count = serializers.IntegerField(min_value=0, required=False, allow_null=True)


# ---------------------------------------------------------------- profiles
class CreatorProfileSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()
    categories = CreatorCategorySerializer(many=True, read_only=True)
    linked_accounts = serializers.SerializerMethodField()
    is_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = CreatorProfile
        fields = (
            "id",
            "user",
            "headline",
            "bio",
            "categories",
            "city",
            "country",
            "languages",
            "open_to_sponsorships",
            "business_email",
            "is_verified",
            "verification_status",
            "verified_at",
            "verified_reach",
            "linked_accounts",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(CreatorPersonSerializer(allow_null=True))
    def get_user(self, obj: CreatorProfile) -> dict[str, Any] | None:
        return person(obj.user)

    @extend_schema_field(CreatorLinkedAccountSerializer(many=True))
    def get_linked_accounts(self, obj: CreatorProfile) -> list[dict[str, Any]]:
        return CreatorLinkedAccountSerializer(obj.linked_accounts.filter(is_public=True), many=True).data


class CreatorOwnProfileSerializer(CreatorProfileSerializer):
    class Meta(CreatorProfileSerializer.Meta):
        fields = (*CreatorProfileSerializer.Meta.fields, "status", "is_discoverable")
        read_only_fields = fields


class CreatorProfileWriteSerializer(serializers.Serializer):
    headline = serializers.CharField(max_length=120, required=False, allow_blank=True)
    bio = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    categories = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=10)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False, allow_blank=True)
    languages = serializers.ListField(child=serializers.CharField(max_length=10), required=False, max_length=10)
    is_discoverable = serializers.BooleanField(required=False)
    open_to_sponsorships = serializers.BooleanField(required=False)
    business_email = serializers.EmailField(required=False, allow_blank=True)
    status = serializers.ChoiceField(choices=ProfileStatus.choices, required=False)


# ------------------------------------------------------------ verification
class CreatorVerificationRequestSerializer(StrictModelSerializer):
    profile = serializers.SerializerMethodField()

    class Meta:
        model = VerificationRequest
        fields = ("id", "profile", "status", "statement", "links", "decision_reason", "reviewed_at", "created_at")
        read_only_fields = fields

    @extend_schema_field(CreatorPersonSerializer(allow_null=True))
    def get_profile(self, obj: VerificationRequest) -> dict[str, Any] | None:
        return person(obj.profile.user)


class CreatorVerificationCreateSerializer(serializers.Serializer):
    statement = serializers.CharField(max_length=3000)
    links = serializers.ListField(child=serializers.CharField(max_length=300), required=False, max_length=10)


class CreatorReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


# --------------------------------------------------------------- media kit
class CreatorMediaKitSerializer(StrictModelSerializer):
    profile = serializers.SerializerMethodField()
    platform_stats = serializers.SerializerMethodField()

    class Meta:
        model = MediaKit
        fields = ("profile", "summary", "audience", "rates", "highlights", "platform_stats", "updated_at")
        read_only_fields = fields

    @extend_schema_field(CreatorProfileSerializer)
    def get_profile(self, obj: MediaKit) -> dict[str, Any]:
        return CreatorProfileSerializer(obj.profile).data

    def get_platform_stats(self, obj: MediaKit) -> dict[str, Any] | None:
        return self.context.get("platform_stats") if obj.show_platform_stats else None


class CreatorOwnMediaKitSerializer(CreatorMediaKitSerializer):
    class Meta(CreatorMediaKitSerializer.Meta):
        fields = (*CreatorMediaKitSerializer.Meta.fields, "visibility", "share_token", "show_platform_stats")
        read_only_fields = fields


class CreatorMediaKitWriteSerializer(serializers.Serializer):
    visibility = serializers.ChoiceField(choices=KitVisibility.choices, required=False)
    summary = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    audience = serializers.JSONField(required=False)
    rates = serializers.JSONField(required=False)
    highlights = serializers.JSONField(required=False)
    show_platform_stats = serializers.BooleanField(required=False)


# --------------------------------------------------------------- campaigns
class CreatorScopeRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class CreatorCampaignSerializer(StrictModelSerializer):
    categories = CreatorCategorySerializer(many=True, read_only=True)
    sponsor = serializers.SerializerMethodField()
    slots_left = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta:
        model = Campaign
        fields = (
            "id",
            "brand_name",
            "title",
            "brief",
            "categories",
            "sponsor",
            "status",
            "visibility",
            "slots",
            "slots_left",
            "budget_minor",
            "currency",
            "deliverables_summary",
            "application_deadline",
            "starts_on",
            "ends_on",
            "verified_only",
            "min_verified_reach",
            "disclosure_required",
            "published_at",
            "viewer",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(CreatorScopeRefSerializer(allow_null=True))
    def get_sponsor(self, obj: Campaign) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None

    def get_slots_left(self, obj: Campaign) -> int | None:
        return None if obj.slots is None else max(obj.slots - obj.accepted_count, 0)

    @extend_schema_field(serializers.DictField())
    def get_viewer(self, obj: Campaign) -> dict[str, Any]:
        participation = (self.context.get("participations") or {}).get(obj.pk)
        return {
            "can_manage": bool((self.context.get("managed") or {}).get(obj.pk)),
            "participation_id": participation.pk if participation else None,
            "participation_status": participation.status if participation else None,
        }


class CreatorCampaignWriteSerializer(serializers.Serializer):
    brand_name = serializers.CharField(max_length=120)
    title = serializers.CharField(max_length=160)
    brief = serializers.CharField(max_length=10000)
    categories = serializers.ListField(child=serializers.CharField(max_length=40), required=False, max_length=10)
    visibility = serializers.ChoiceField(choices=CampaignVisibility.choices, required=False)
    slots = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    budget_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)
    deliverables_summary = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    application_deadline = serializers.DateTimeField(required=False, allow_null=True)
    starts_on = serializers.DateField(required=False, allow_null=True)
    ends_on = serializers.DateField(required=False, allow_null=True)
    verified_only = serializers.BooleanField(required=False)
    min_verified_reach = serializers.IntegerField(min_value=0, required=False)
    disclosure_required = serializers.BooleanField(required=False)
    sponsor_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)
    sponsor_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="", write_only=True)


class CreatorParticipationSerializer(StrictModelSerializer):
    creator = serializers.SerializerMethodField()
    campaign = serializers.SerializerMethodField()

    class Meta:
        model = Participation
        fields = (
            "id",
            "campaign",
            "creator",
            "status",
            "pitch",
            "proposed_fee_minor",
            "agreed_fee_minor",
            "fee_paid_at",
            "note",
            "decided_at",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(serializers.DictField())
    def get_creator(self, obj: Participation) -> dict[str, Any]:
        profile = obj.profile
        return {
            "profile_id": profile.pk,
            "user": person(profile.user),
            "is_verified": profile.is_verified,
            "verified_reach": profile.verified_reach,
        }

    @extend_schema_field(serializers.DictField())
    def get_campaign(self, obj: Participation) -> dict[str, Any]:
        campaign = obj.campaign
        return {
            "id": campaign.pk,
            "title": campaign.title,
            "brand_name": campaign.brand_name,
            "currency": campaign.currency,
        }


class CreatorApplySerializer(serializers.Serializer):
    pitch = serializers.CharField(max_length=3000)
    proposed_fee_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)


class CreatorInviteSerializer(serializers.Serializer):
    profile_id = serializers.UUIDField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CreatorDecisionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["shortlist", "accept", "decline", "complete", "cancel", "withdraw"])
    fee_minor = serializers.IntegerField(min_value=0, required=False, allow_null=True)
    note = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class CreatorDeliverableSerializer(StrictModelSerializer):
    class Meta:
        model = Deliverable
        fields = (
            "id",
            "title",
            "description",
            "due_at",
            "status",
            "submission_url",
            "submission_note",
            "disclosure_confirmed",
            "submitted_at",
            "reviewed_at",
            "review_note",
        )
        read_only_fields = fields


class CreatorDeliverableWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    due_at = serializers.DateTimeField(required=False, allow_null=True)


class CreatorSubmitSerializer(serializers.Serializer):
    url = serializers.URLField(max_length=500)
    note = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")
    disclosure_confirmed = serializers.BooleanField(default=False)


class CreatorReviewSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")
