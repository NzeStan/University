from __future__ import annotations

from rest_framework import serializers

from university.core.api.serializers import StrictModelSerializer
from university.payments.models import PaymentIntent, Payout, Refund


class PaymentIntentSerializer(StrictModelSerializer):
    class Meta:
        model = PaymentIntent
        fields = (
            "reference",
            "purpose",
            "object_id",
            "description",
            "amount_minor",
            "currency",
            "provider",
            "status",
            "checkout_url",
            "amount_refunded_minor",
            "failure_reason",
            "expires_at",
            "paid_at",
            "created_at",
        )
        read_only_fields = fields


class PaymentCheckoutSerializer(serializers.Serializer):
    purpose = serializers.CharField(max_length=64)
    object_id = serializers.CharField(max_length=64)
    provider = serializers.CharField(max_length=32, required=False, allow_blank=True)
    callback_url = serializers.URLField(max_length=500, required=False, allow_blank=True)


class PaymentRefundSerializer(StrictModelSerializer):
    class Meta:
        model = Refund
        fields = ("reference", "amount_minor", "status", "reason", "created_at", "completed_at")
        read_only_fields = fields


class PaymentRefundCreateSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    reason = serializers.CharField(max_length=255)


class PaymentProviderSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class PaymentBalanceSerializer(serializers.Serializer):
    currency = serializers.CharField()
    held = serializers.IntegerField(help_text="In escrow, waiting for release.")
    available = serializers.IntegerField(help_text="Withdrawable.")
    payout = serializers.IntegerField(help_text="Committed to requested payouts.")


class PayoutSerializer(StrictModelSerializer):
    class Meta:
        model = Payout
        fields = (
            "id",
            "amount_minor",
            "currency",
            "status",
            "destination",
            "external_reference",
            "note",
            "processed_at",
            "created_at",
        )
        read_only_fields = fields


class PayoutCreateSerializer(serializers.Serializer):
    amount_minor = serializers.IntegerField(min_value=1)
    currency = serializers.RegexField(r"^[A-Z]{3}$")
    destination = serializers.CharField(max_length=120)


class PayoutDecisionSerializer(serializers.Serializer):
    external_reference = serializers.CharField(max_length=128, required=False, allow_blank=True, default="")
    note = serializers.CharField(max_length=255, required=False, allow_blank=True, default="")
