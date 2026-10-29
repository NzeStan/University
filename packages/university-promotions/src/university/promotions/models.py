from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel
from university.core.uploads import uuid_upload_to


class CampaignKind(models.TextChoices):
    BOOST = "boost", _("Boost something I posted")
    AD = "ad", _("Advert")


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PENDING_PAYMENT = "pending_payment", _("Awaiting payment")
    IN_REVIEW = "in_review", _("In review")
    ACTIVE = "active", _("Running")
    PAUSED = "paused", _("Paused")
    COMPLETED = "completed", _("Completed")
    REJECTED = "rejected", _("Rejected")


class CallToAction(models.TextChoices):
    LEARN_MORE = "learn_more", _("Learn more")
    SIGN_UP = "sign_up", _("Sign up")
    SHOP_NOW = "shop_now", _("Shop now")
    REGISTER = "register", _("Register")
    APPLY = "apply", _("Apply")
    LISTEN = "listen", _("Listen")


class Campaign(BaseModel):
    advertiser = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="promotion_campaigns"
    )
    name = models.CharField(max_length=100)
    kind = models.CharField(max_length=8, choices=CampaignKind.choices)
    # Boosts: one of the advertiser's own items.
    content_type = models.CharField(max_length=64, blank=True)
    object_id = models.CharField(max_length=64, blank=True)
    # Adverts: a reviewed creative.
    headline = models.CharField(max_length=90, blank=True)
    body = models.CharField(max_length=240, blank=True)
    image = models.FileField(upload_to=uuid_upload_to("promotions"), blank=True, max_length=255)
    call_to_action = models.CharField(max_length=16, choices=CallToAction.choices, default=CallToAction.LEARN_MORE)
    destination_url = models.URLField(blank=True)
    # Targeting: institutions (empty: everyone) and placements.
    institution_ids = models.JSONField(default=list, blank=True)
    placements = models.JSONField(default=list, blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    budget_minor = models.PositiveBigIntegerField()
    currency = models.CharField(max_length=3, default="NGN")
    cpm_minor = models.PositiveBigIntegerField(help_text=_("Price per 1,000 impressions, fixed when submitted."))
    status = models.CharField(max_length=16, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT)
    review_note = models.CharField(max_length=500, blank=True)
    reviewed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    reviewed_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=64, blank=True)
    impressions = models.PositiveBigIntegerField(default=0)
    clicks = models.PositiveBigIntegerField(default=0)

    class Meta:
        verbose_name = _("promotion campaign")
        indexes = [
            models.Index(fields=["status", "starts_at", "ends_at"], name="univ_promo_serving"),
            models.Index(fields=["advertiser", "-created_at"], name="univ_promo_advertiser"),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def impression_cap(self) -> int:
        return (self.budget_minor * 1000) // max(self.cpm_minor, 1)

    @property
    def spent_minor(self) -> int:
        return min(self.budget_minor, (self.impressions * self.cpm_minor) // 1000)


class DailyStat(models.Model):
    """Aggregate delivery per campaign per day. No viewer is ever recorded."""

    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="daily_stats")
    date = models.DateField()
    impressions = models.PositiveIntegerField(default=0)
    clicks = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("campaign daily stat")
        constraints = [models.UniqueConstraint(fields=["campaign", "date"], name="univ_promo_daily_unique")]

    def __str__(self) -> str:
        return f"{self.campaign_id} {self.date}"
