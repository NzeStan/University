from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class IntentStatus(models.TextChoices):
    #: Checkout created; waiting for the payer.
    PENDING = "pending", _("Pending")
    SUCCEEDED = "succeeded", _("Succeeded")
    FAILED = "failed", _("Failed")
    CANCELLED = "cancelled", _("Cancelled")
    EXPIRED = "expired", _("Expired")
    PARTIALLY_REFUNDED = "partially_refunded", _("Partially refunded")
    REFUNDED = "refunded", _("Refunded")


PAID_STATUSES = frozenset({IntentStatus.SUCCEEDED, IntentStatus.PARTIALLY_REFUNDED})


class RefundStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUCCEEDED = "succeeded", _("Succeeded")
    FAILED = "failed", _("Failed")


class PayoutStatus(models.TextChoices):
    REQUESTED = "requested", _("Requested")
    PAID = "paid", _("Paid")
    REJECTED = "rejected", _("Rejected")
    CANCELLED = "cancelled", _("Cancelled")


class EntryKind(models.TextChoices):
    PAYMENT = "payment", _("Payment")
    RELEASE = "release", _("Escrow release")
    REFUND = "refund", _("Refund")
    PAYOUT_REQUESTED = "payout_requested", _("Payout requested")
    PAYOUT_PAID = "payout_paid", _("Payout paid")
    PAYOUT_REVERSED = "payout_reversed", _("Payout reversed")


PLATFORM_REVENUE = "platform:revenue"
PLATFORM_PAYOUTS = "platform:payouts"


def provider_account(provider: str) -> str:
    return f"provider:{provider}"


def payee_account(user_id: object, bucket: str) -> str:
    """``bucket`` is ``held`` (escrow), ``available`` or ``payout``."""
    return f"payee:{user_id}:{bucket}"
