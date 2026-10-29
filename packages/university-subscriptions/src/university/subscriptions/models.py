from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel


class Interval(models.TextChoices):
    MONTH = "month", _("Monthly")
    YEAR = "year", _("Yearly")


class SubscriptionStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", _("Awaiting first payment")
    ACTIVE = "active", _("Active")
    PAST_DUE = "past_due", _("Renewal due (grace period)")
    EXPIRED = "expired", _("Expired")
    ABANDONED = "abandoned", _("Never paid")


LIVE = (SubscriptionStatus.PENDING_PAYMENT, SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)
ENTITLED = (SubscriptionStatus.ACTIVE, SubscriptionStatus.PAST_DUE)


class Subscription(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="subscriptions")
    plan = models.CharField(max_length=32)
    interval = models.CharField(max_length=8, choices=Interval.choices)
    currency = models.CharField(max_length=3)
    status = models.CharField(
        max_length=16, choices=SubscriptionStatus.choices, default=SubscriptionStatus.PENDING_PAYMENT
    )
    current_period_start = models.DateTimeField(null=True, blank=True)
    current_period_end = models.DateTimeField(null=True, blank=True)
    #: The member doesn't intend to renew: no reminders; it simply ends.
    cancel_at_period_end = models.BooleanField(default=False)
    #: The period end a reminder was last sent for (one reminder per period).
    reminded_for = models.DateTimeField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["user"], condition=Q(status__in=LIVE), name="univ_subs_one_live_per_user"),
        ]
        indexes = [models.Index(fields=["status", "current_period_end"], name="univ_subs_status_end")]

    def __str__(self) -> str:
        return f"{self.plan} ({self.status})"


class Period(BaseModel):
    """One paid period: the receipt trail for a subscription."""

    subscription = models.ForeignKey(Subscription, on_delete=models.CASCADE, related_name="periods")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    amount_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3)
    payment_reference = models.CharField(max_length=64, unique=True)

    class Meta:
        ordering = ("-starts_at",)
