from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.subscriptions.conf import plans, subscriptions_settings
from university.subscriptions.models import Interval, Period, Subscription


class SubscriptionEntitlementSerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()


class SubscriptionPriceSerializer(serializers.Serializer):
    interval = serializers.ChoiceField(choices=Interval.choices)
    currency = serializers.CharField()
    amount_minor = serializers.IntegerField()


class SubscriptionPlanSerializer(serializers.Serializer):
    key = serializers.CharField()
    name = serializers.CharField()
    description = serializers.CharField()
    prices = SubscriptionPriceSerializer(many=True)
    entitlements = SubscriptionEntitlementSerializer(many=True)


def plan_data(key: str, plan: dict[str, Any]) -> dict[str, Any]:
    labels = subscriptions_settings.get("ENTITLEMENT_LABELS") or {}
    return {
        "key": key,
        "name": plan.get("name", key),
        "description": plan.get("description", ""),
        "prices": [
            {"interval": interval, "currency": currency, "amount_minor": int(amount)}
            for interval, by_currency in (plan.get("prices") or {}).items()
            for currency, amount in by_currency.items()
        ],
        "entitlements": [{"key": k, "label": labels.get(k, k)} for k in plan.get("entitlements", [])],
    }


class SubscriptionPeriodSerializer(serializers.ModelSerializer):
    class Meta:
        model = Period
        fields = ("starts_at", "ends_at", "amount_minor", "currency", "payment_reference")
        read_only_fields = fields


class SubscriptionPaymentHintSerializer(serializers.Serializer):
    """Pass to POST /payments/checkout/ to pay what's due."""

    purpose = serializers.CharField()
    object_id = serializers.CharField()
    amount_minor = serializers.IntegerField()
    currency = serializers.CharField()


class SubscriptionSerializer(serializers.ModelSerializer):
    plan_name = serializers.SerializerMethodField()
    payment_due = serializers.SerializerMethodField()
    periods = serializers.SerializerMethodField()

    class Meta:
        model = Subscription
        fields = (
            "id", "plan", "plan_name", "interval", "currency", "status", "current_period_start", "current_period_end",
            "cancel_at_period_end", "payment_due", "periods", "created_at",
        )  # fmt: skip
        read_only_fields = fields

    def get_plan_name(self, obj: Subscription) -> str:
        return str(plans().get(obj.plan, {}).get("name", obj.plan))

    @extend_schema_field(SubscriptionPaymentHintSerializer(allow_null=True))
    def get_payment_due(self, obj: Subscription) -> dict[str, Any] | None:
        from university.subscriptions.services import PURPOSE, amount_due

        due = amount_due(obj)
        if due is None:
            return None
        return {"purpose": PURPOSE, "object_id": str(obj.pk), "amount_minor": due, "currency": obj.currency}

    @extend_schema_field(SubscriptionPeriodSerializer(many=True))
    def get_periods(self, obj: Subscription) -> list[dict[str, Any]]:
        return SubscriptionPeriodSerializer(obj.periods.all()[:12], many=True).data


class MySubscriptionSerializer(serializers.Serializer):
    subscription = SubscriptionSerializer(allow_null=True)
    entitlements = serializers.ListField(child=serializers.CharField())


class SubscribeSerializer(serializers.Serializer):
    plan = serializers.CharField(max_length=32)
    interval = serializers.ChoiceField(choices=Interval.choices)
    currency = serializers.CharField(max_length=3, default="NGN")


class CancelSerializer(serializers.Serializer):
    cancel = serializers.BooleanField(default=True, help_text="False to keep renewing (undo a cancellation).")
