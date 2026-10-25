"""Payments data model.

::

    PaymentIntent ──┬── Refund
                    └── LedgerEntry ── (also Refund / Payout)
    Payout

The ledger is double-entry: every posting is a group of entries that sums to
zero, so balances (provider cash, escrow held for sellers, money available to
sellers, platform revenue) are always derivable and auditable. Entries are
never updated or deleted.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel
from university.payments.constants import EntryKind, IntentStatus, PayoutStatus, RefundStatus

USER = settings.AUTH_USER_MODEL


class PaymentIntent(BaseModel):
    #: Our reference, given to the provider and shown to the payer.
    reference = models.CharField(max_length=40, unique=True)
    payer = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="payment_intents")
    #: The payable purpose and object (see university.core.payables).
    purpose = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    description = models.CharField(max_length=200)
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    platform_fee_minor = models.PositiveBigIntegerField(default=0)
    payee = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    escrow = models.BooleanField(default=False)
    provider = models.CharField(max_length=32)
    provider_reference = models.CharField(max_length=255, blank=True)
    provider_transaction_id = models.CharField(max_length=128, blank=True)
    checkout_url = models.URLField(max_length=1000, blank=True)
    status = models.CharField(max_length=20, choices=IntentStatus.choices, default=IntentStatus.PENDING)
    failure_reason = models.CharField(max_length=64, blank=True)
    amount_refunded_minor = models.PositiveBigIntegerField(default=0)
    channel = models.CharField(max_length=32, blank=True)
    expires_at = models.DateTimeField()
    paid_at = models.DateTimeField(null=True, blank=True)
    released_at = models.DateTimeField(null=True, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("payment intent")
        indexes = [
            models.Index(fields=["purpose", "object_id", "status"], name="univ_pay_intent_object"),
            models.Index(fields=["payer", "-created_at"], name="univ_pay_intent_payer"),
            models.Index(fields=["status", "expires_at"], name="univ_pay_intent_expiry"),
        ]
        constraints = [
            # A provider transaction settles exactly one intent.
            models.UniqueConstraint(
                fields=["provider", "provider_transaction_id"],
                condition=~Q(provider_transaction_id=""),
                name="univ_pay_provider_txn_unique",
            ),
            # One open checkout per payer and object (retries reuse it).
            models.UniqueConstraint(
                fields=["purpose", "object_id", "payer"],
                condition=Q(status=IntentStatus.PENDING),
                name="univ_pay_one_pending_intent",
            ),
            models.CheckConstraint(
                condition=Q(amount_refunded_minor__lte=models.F("amount_minor")), name="univ_pay_refund_within_amount"
            ),
            models.CheckConstraint(
                condition=Q(platform_fee_minor__lte=models.F("amount_minor")), name="univ_pay_fee_within_amount"
            ),
        ]

    def __str__(self) -> str:
        return self.reference

    @property
    def refundable_minor(self) -> int:
        return self.amount_minor - self.amount_refunded_minor


class Refund(BaseModel):
    intent = models.ForeignKey(PaymentIntent, on_delete=models.PROTECT, related_name="refunds")
    reference = models.CharField(max_length=40, unique=True)
    amount_minor = models.PositiveBigIntegerField()
    status = models.CharField(max_length=16, choices=RefundStatus.choices, default=RefundStatus.PENDING)
    reason = models.CharField(max_length=255, blank=True)
    provider_refund_id = models.CharField(max_length=128, blank=True)
    requested_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    attempts = models.PositiveSmallIntegerField(default=0)
    error = models.CharField(max_length=64, blank=True)
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("refund")
        indexes = [models.Index(fields=["status", "created_at"], name="univ_pay_refund_status")]

    def __str__(self) -> str:
        return self.reference


class Payout(BaseModel):
    payee = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="payouts")
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    status = models.CharField(max_length=16, choices=PayoutStatus.choices, default=PayoutStatus.REQUESTED)
    #: A masked description of the destination (e.g. "GTBank ••••1234"); never full account numbers.
    destination = models.CharField(max_length=120)
    processed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    processed_at = models.DateTimeField(null=True, blank=True)
    external_reference = models.CharField(max_length=128, blank=True)
    note = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("payout")
        indexes = [models.Index(fields=["status", "created_at"], name="univ_pay_payout_status")]

    def __str__(self) -> str:
        return f"Payout {self.amount_minor} {self.currency} to {self.payee_id}"


class LedgerEntry(models.Model):
    """One leg of a balanced posting. Positive = debit, negative = credit."""

    id = models.BigAutoField(primary_key=True)
    group = models.UUIDField(db_index=True)
    account = models.CharField(max_length=100)
    amount_minor = models.BigIntegerField()
    currency = models.CharField(max_length=3)
    kind = models.CharField(max_length=20, choices=EntryKind.choices)
    intent = models.ForeignKey(PaymentIntent, null=True, blank=True, on_delete=models.PROTECT, related_name="entries")
    refund = models.ForeignKey(Refund, null=True, blank=True, on_delete=models.PROTECT, related_name="entries")
    payout = models.ForeignKey(Payout, null=True, blank=True, on_delete=models.PROTECT, related_name="entries")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("ledger entry")
        verbose_name_plural = _("ledger entries")
        indexes = [models.Index(fields=["account", "currency"], name="univ_pay_ledger_account")]

    def __str__(self) -> str:
        return f"{self.account} {self.amount_minor:+d} {self.currency}"
