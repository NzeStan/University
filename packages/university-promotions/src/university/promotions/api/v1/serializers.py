from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.promotions.models import CallToAction, Campaign, CampaignKind
from university.users.refs import PersonRefSerializer, person_ref


class PromotionCampaignSerializer(StrictModelSerializer):
    image_url = serializers.SerializerMethodField()
    impression_cap = serializers.IntegerField(read_only=True)
    spent_minor = serializers.IntegerField(read_only=True)

    class Meta:
        model = Campaign
        fields = (
            "id", "name", "kind", "content_type", "object_id", "headline", "body", "image_url", "call_to_action",
            "destination_url", "institution_ids", "placements", "starts_at", "ends_at", "budget_minor", "currency",
            "cpm_minor", "impression_cap", "status", "review_note", "impressions", "clicks", "spent_minor",
            "created_at",
        )  # fmt: skip
        read_only_fields = fields

    def get_image_url(self, obj: Campaign) -> str | None:
        return obj.image.url if obj.image else None


class PromotionCampaignWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    kind = serializers.ChoiceField(choices=CampaignKind.choices)
    content_type = serializers.CharField(max_length=64, required=False, allow_blank=True)
    object_id = serializers.CharField(max_length=64, required=False, allow_blank=True)
    headline = serializers.CharField(max_length=90, required=False, allow_blank=True)
    body = serializers.CharField(max_length=240, required=False, allow_blank=True)
    call_to_action = serializers.ChoiceField(choices=CallToAction.choices, default=CallToAction.LEARN_MORE)
    destination_url = serializers.URLField(required=False, allow_blank=True)
    institution_ids = serializers.ListField(child=serializers.CharField(max_length=64), required=False, max_length=50)
    placements = serializers.ListField(child=serializers.CharField(max_length=32), min_length=1, max_length=10)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    budget_minor = serializers.IntegerField(min_value=1)
    currency = serializers.CharField(max_length=3, default="NGN")


class PromotionImageSerializer(serializers.Serializer):
    file = serializers.FileField()


class PromotionReviewSerializer(serializers.Serializer):
    approve = serializers.BooleanField()
    note = serializers.CharField(max_length=500, required=False, allow_blank=True)


class PromotionContentRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class PromotionCreativeSerializer(serializers.Serializer):
    headline = serializers.CharField()
    body = serializers.CharField()
    image_url = serializers.CharField(allow_null=True)
    call_to_action = serializers.CharField()


class PromotedItemSerializer(serializers.Serializer):
    """A sponsored item to show. Always label it with ``label``."""

    token = serializers.CharField(help_text="Send to impressions/ when shown and clicks/ when opened.")
    campaign_id = serializers.UUIDField()
    kind = serializers.CharField()
    label = serializers.CharField()
    advertiser = serializers.SerializerMethodField()
    content = serializers.SerializerMethodField()
    creative = serializers.SerializerMethodField()

    @extend_schema_field(PersonRefSerializer)
    def get_advertiser(self, item: dict[str, Any]) -> dict[str, Any] | None:
        return person_ref(item["campaign"].advertiser)

    @extend_schema_field(PromotionContentRefSerializer(allow_null=True))
    def get_content(self, item: dict[str, Any]) -> dict[str, Any] | None:
        c = item["campaign"]
        return {"type": c.content_type, "id": c.object_id} if c.kind == CampaignKind.BOOST else None

    @extend_schema_field(PromotionCreativeSerializer(allow_null=True))
    def get_creative(self, item: dict[str, Any]) -> dict[str, Any] | None:
        c = item["campaign"]
        if c.kind != CampaignKind.AD:
            return None
        return {
            "headline": c.headline,
            "body": c.body,
            "image_url": c.image.url if c.image else None,
            "call_to_action": c.call_to_action,
        }


class PromotionTokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=1000)


class PromotionClickResultSerializer(serializers.Serializer):
    destination_url = serializers.CharField(allow_null=True)
    content = PromotionContentRefSerializer(allow_null=True)


class PromotionDailyStatSerializer(serializers.Serializer):
    date = serializers.DateField()
    impressions = serializers.IntegerField()
    clicks = serializers.IntegerField()


class PromotionStatsSerializer(serializers.Serializer):
    impressions = serializers.IntegerField()
    clicks = serializers.IntegerField()
    click_through_rate = serializers.FloatField()
    spent_minor = serializers.IntegerField()
    budget_minor = serializers.IntegerField()
    currency = serializers.CharField()
    daily = PromotionDailyStatSerializer(many=True)


class PromotionOptionsSerializer(serializers.Serializer):
    placements = serializers.ListField(child=serializers.CharField())
    boostable = serializers.DictField(child=serializers.CharField())
    cpm_minor = serializers.DictField(child=serializers.IntegerField())
    min_budget_minor = serializers.DictField(child=serializers.IntegerField())
    require_payment = serializers.BooleanField()
