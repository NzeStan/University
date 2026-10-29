from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.marketplace.constants import Condition, DisputeOutcome, Fulfilment, ListingVisibility, PaymentMethod
from university.marketplace.models import Listing, ListingImage, MarketCategory, Order, Review, SellerProfile
from university.users.refs import person_ref


class MarketPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)


def person(user: Any) -> dict[str, Any] | None:
    if user is None or not user.is_active:
        return None
    return person_ref(user)


def _url(context: dict[str, Any], field: Any) -> str:
    url = field.url
    request = context.get("request")
    return request.build_absolute_uri(url) if request is not None and url.startswith("/") else url


class MarketCategorySerializer(StrictModelSerializer):
    parent = serializers.SlugRelatedField(slug_field="key", read_only=True, allow_null=True)

    class Meta:
        model = MarketCategory
        fields = ("key", "name", "parent")
        read_only_fields = fields


class MarketSellerSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()
    rating = serializers.FloatField(read_only=True, allow_null=True)

    class Meta:
        model = SellerProfile
        fields = ("user", "store_name", "about", "rating", "rating_count", "sales_count", "created_at")
        read_only_fields = fields

    @extend_schema_field(MarketPersonSerializer(allow_null=True))
    def get_user(self, obj: SellerProfile) -> dict[str, Any] | None:
        return person(obj.user)


class MarketSellerWriteSerializer(serializers.Serializer):
    store_name = serializers.CharField(max_length=80, required=False)
    about = serializers.CharField(max_length=2000, required=False, allow_blank=True)


class MarketImageSerializer(StrictModelSerializer):
    url = serializers.SerializerMethodField()

    class Meta:
        model = ListingImage
        fields = ("id", "url", "alt_text", "position")
        read_only_fields = fields

    def get_url(self, obj: ListingImage) -> str:
        return _url(self.context, obj.file)


class MarketScopeRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class MarketListingSerializer(StrictModelSerializer):
    seller = serializers.SerializerMethodField()
    category = MarketCategorySerializer(read_only=True)
    images = serializers.SerializerMethodField()
    scope = serializers.SerializerMethodField()
    is_hidden = serializers.SerializerMethodField()

    class Meta:
        model = Listing
        fields = (
            "id",
            "title",
            "description",
            "category",
            "condition",
            "price_minor",
            "currency",
            "quantity",
            "status",
            "visibility",
            "scope",
            "city",
            "location_note",
            "allows_pickup",
            "allows_delivery",
            "delivery_fee_minor",
            "allows_cash_on_pickup",
            "images",
            "seller",
            "is_hidden",
            "published_at",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(MarketPersonSerializer(allow_null=True))
    def get_seller(self, obj: Listing) -> dict[str, Any] | None:
        return person(obj.seller)

    @extend_schema_field(MarketImageSerializer(many=True))
    def get_images(self, obj: Listing) -> list[dict[str, Any]]:
        return MarketImageSerializer(obj.images.all(), many=True, context=self.context).data

    @extend_schema_field(MarketScopeRefSerializer(allow_null=True))
    def get_scope(self, obj: Listing) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None

    def get_is_hidden(self, obj: Listing) -> bool:
        return obj.hidden_at is not None


class MarketListingWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=120)
    description = serializers.CharField(max_length=10000, required=False, allow_blank=True)
    category = serializers.CharField(max_length=40)
    condition = serializers.ChoiceField(choices=Condition.choices, required=False)
    price_minor = serializers.IntegerField(min_value=0, max_value=10**12)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)
    quantity = serializers.IntegerField(min_value=0, max_value=100000, required=False)
    visibility = serializers.ChoiceField(choices=ListingVisibility.choices, required=False)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    location_note = serializers.CharField(max_length=160, required=False, allow_blank=True)
    allows_pickup = serializers.BooleanField(required=False)
    allows_delivery = serializers.BooleanField(required=False)
    delivery_fee_minor = serializers.IntegerField(min_value=0, required=False)
    allows_cash_on_pickup = serializers.BooleanField(required=False)
    scope_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)
    scope_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="", write_only=True)


class MarketListingActionSerializer(serializers.Serializer):
    action = serializers.ChoiceField(choices=["publish", "pause", "remove"])


class MarketImageUploadSerializer(serializers.Serializer):
    file = serializers.FileField()
    alt_text = serializers.CharField(max_length=200, required=False, allow_blank=True, default="")


class MarketOrderSerializer(StrictModelSerializer):
    buyer = serializers.SerializerMethodField()
    seller = serializers.SerializerMethodField()
    delivery_details = serializers.SerializerMethodField()
    reviewed = serializers.SerializerMethodField()

    class Meta:
        model = Order
        fields = (
            "id",
            "reference",
            "listing",
            "title",
            "unit_price_minor",
            "quantity",
            "delivery_fee_minor",
            "total_minor",
            "currency",
            "fulfilment",
            "payment_method",
            "delivery_details",
            "status",
            "buyer",
            "seller",
            "expires_at",
            "paid_at",
            "fulfilled_at",
            "auto_complete_at",
            "completed_at",
            "cancelled_at",
            "cancel_reason",
            "disputed_at",
            "dispute_reason",
            "resolution",
            "reviewed",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(MarketPersonSerializer(allow_null=True))
    def get_buyer(self, obj: Order) -> dict[str, Any] | None:
        return person(obj.buyer)

    @extend_schema_field(MarketPersonSerializer(allow_null=True))
    def get_seller(self, obj: Order) -> dict[str, Any] | None:
        return person(obj.seller)

    def get_delivery_details(self, obj: Order) -> str | None:
        """Only the buyer and seller see the address; mediators don't need it."""
        user = self.context.get("request").user if self.context.get("request") else None
        return obj.delivery_details if user is not None and user.pk in (obj.buyer_id, obj.seller_id) else None

    def get_reviewed(self, obj: Order) -> bool:
        return hasattr(obj, "review")


class MarketOrderCreateSerializer(serializers.Serializer):
    listing = serializers.UUIDField()
    quantity = serializers.IntegerField(min_value=1, default=1)
    fulfilment = serializers.ChoiceField(choices=Fulfilment.choices, default=Fulfilment.PICKUP)
    payment_method = serializers.ChoiceField(choices=PaymentMethod.choices, default=PaymentMethod.ONLINE)
    delivery_details = serializers.CharField(max_length=1000, required=False, allow_blank=True, default="")


class MarketReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class MarketResolveSerializer(serializers.Serializer):
    outcome = serializers.ChoiceField(choices=DisputeOutcome.choices)
    refund_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    note = serializers.CharField(max_length=500)


class MarketReviewSerializer(StrictModelSerializer):
    reviewer = serializers.SerializerMethodField()

    class Meta:
        model = Review
        fields = ("id", "rating", "comment", "reviewer", "seller_reply", "replied_at", "created_at")
        read_only_fields = fields

    @extend_schema_field(MarketPersonSerializer(allow_null=True))
    def get_reviewer(self, obj: Review) -> dict[str, Any] | None:
        return person(obj.reviewer)


class MarketReviewCreateSerializer(serializers.Serializer):
    rating = serializers.IntegerField(min_value=1, max_value=5)
    comment = serializers.CharField(max_length=2000, required=False, allow_blank=True, default="")


class MarketReplySerializer(serializers.Serializer):
    reply = serializers.CharField(max_length=2000)
