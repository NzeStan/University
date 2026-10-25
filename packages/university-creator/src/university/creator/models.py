"""Creator data model.

::

    CreatorProfile ──┬── LinkedAccount ── LinkedAccountSnapshot (daily follower counts)
                     ├── VerificationRequest
                     ├── MediaKit
                     ├── CreatorDailyStat                     (aggregates only)
                     └── Participation ── Deliverable
    Campaign ────────┘

Analytics are stored as per-day counters (no viewer identities), so they can
be kept for growth charts without retaining raw activity.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.creator.constants import (
    CampaignStatus,
    CampaignVisibility,
    CountSource,
    DeliverableStatus,
    KitVisibility,
    OwnershipStatus,
    ParticipationStatus,
    ProfileStatus,
    RequestStatus,
    VerificationStatus,
)

USER = settings.AUTH_USER_MODEL


class CreatorCategory(models.Model):
    key = models.SlugField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("creator category")
        verbose_name_plural = _("creator categories")
        ordering = ("position", "name")

    def __str__(self) -> str:
        return self.name


class CreatorProfile(BaseModel):
    user = models.OneToOneField(USER, on_delete=models.CASCADE, related_name="creator_profile")
    headline = models.CharField(max_length=120, blank=True)
    bio = models.TextField(blank=True)
    categories = models.ManyToManyField(CreatorCategory, blank=True, related_name="creators")
    city = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=2, blank=True)
    languages = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=ProfileStatus.choices, default=ProfileStatus.ACTIVE)
    #: Listed in creator discovery (the user's profile privacy still applies).
    is_discoverable = models.BooleanField(default=True)
    open_to_sponsorships = models.BooleanField(default=True)
    business_email = models.EmailField(blank=True)
    verification_status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.UNVERIFIED
    )
    verified_at = models.DateTimeField(null=True, blank=True)
    #: Sum of trusted (provider- or reviewer-confirmed) follower counts across linked accounts.
    verified_reach = models.PositiveBigIntegerField(default=0)

    class Meta:
        verbose_name = _("creator profile")
        indexes = [
            models.Index(fields=["status", "is_discoverable", "-verified_reach"], name="univ_crt_discovery"),
            models.Index(fields=["verification_status"], name="univ_crt_verification"),
        ]

    def __str__(self) -> str:
        return f"Creator {self.user_id}"

    @property
    def is_verified(self) -> bool:
        return self.verification_status == VerificationStatus.VERIFIED


class LinkedAccount(BaseModel):
    profile = models.ForeignKey(CreatorProfile, on_delete=models.CASCADE, related_name="linked_accounts")
    provider = models.CharField(max_length=32)
    handle = models.CharField(max_length=100)
    #: Lower-cased handle, for uniqueness of verified accounts.
    handle_key = models.CharField(max_length=100)
    external_id = models.CharField(max_length=128, blank=True)
    url = models.URLField(max_length=300, blank=True)
    display_name = models.CharField(max_length=150, blank=True)
    follower_count = models.PositiveBigIntegerField(null=True, blank=True)
    count_source = models.CharField(max_length=16, choices=CountSource.choices, default=CountSource.SELF_REPORTED)
    ownership = models.CharField(max_length=16, choices=OwnershipStatus.choices, default=OwnershipStatus.UNVERIFIED)
    #: Placed by the creator in their bio on the platform to prove ownership. Not a secret.
    challenge = models.CharField(max_length=32)
    verified_at = models.DateTimeField(null=True, blank=True)
    last_synced_at = models.DateTimeField(null=True, blank=True)
    is_public = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("linked account")
        constraints = [
            models.UniqueConstraint(fields=["profile", "provider", "handle_key"], name="univ_crt_account_unique"),
            # One creator per verified external account: no impersonation.
            models.UniqueConstraint(
                fields=["provider", "handle_key"],
                condition=Q(ownership=OwnershipStatus.VERIFIED),
                name="univ_crt_verified_account_unique",
            ),
        ]
        indexes = [models.Index(fields=["ownership", "last_synced_at"], name="univ_crt_account_sync")]

    def __str__(self) -> str:
        return f"{self.provider}:{self.handle}"


class LinkedAccountSnapshot(models.Model):
    account = models.ForeignKey(LinkedAccount, on_delete=models.CASCADE, related_name="snapshots")
    date = models.DateField()
    follower_count = models.PositiveBigIntegerField()

    class Meta:
        verbose_name = _("linked account snapshot")
        constraints = [models.UniqueConstraint(fields=["account", "date"], name="univ_crt_snapshot_unique")]

    def __str__(self) -> str:
        return f"{self.account_id} {self.date}: {self.follower_count}"


class VerificationRequest(BaseModel):
    profile = models.ForeignKey(CreatorProfile, on_delete=models.CASCADE, related_name="verification_requests")
    status = models.CharField(max_length=16, choices=RequestStatus.choices, default=RequestStatus.PENDING)
    statement = models.TextField()
    #: Supporting links (press, portfolio). Linked accounts are reviewed separately.
    links = models.JSONField(default=list, blank=True)
    reviewed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reviewed_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("verification request")
        constraints = [
            models.UniqueConstraint(
                fields=["profile"], condition=Q(status=RequestStatus.PENDING), name="univ_crt_one_pending_request"
            )
        ]
        indexes = [models.Index(fields=["status", "created_at"], name="univ_crt_request_queue")]

    def __str__(self) -> str:
        return f"Verification {self.status} for {self.profile_id}"


class MediaKit(BaseModel):
    profile = models.OneToOneField(CreatorProfile, on_delete=models.CASCADE, related_name="media_kit")
    visibility = models.CharField(max_length=16, choices=KitVisibility.choices, default=KitVisibility.PRIVATE)
    #: For unlisted sharing; rotate to revoke old links.
    share_token = models.CharField(max_length=64, unique=True)
    summary = models.TextField(blank=True)
    #: Self-reported audience, e.g. {"age": {"18-24": 60}, "countries": {"NG": 70}, "gender": {...}}.
    audience = models.JSONField(default=dict, blank=True)
    #: [{"deliverable": "Instagram reel", "price_minor": 5000000, "currency": "NGN", "notes": ""}]
    rates = models.JSONField(default=list, blank=True)
    #: Past collaborations: [{"brand": ..., "title": ..., "url": ..., "year": ...}]
    highlights = models.JSONField(default=list, blank=True)
    show_platform_stats = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("media kit")

    def __str__(self) -> str:
        return f"Media kit of {self.profile_id}"


class CreatorDailyStat(models.Model):
    profile = models.ForeignKey(CreatorProfile, on_delete=models.CASCADE, related_name="daily_stats")
    date = models.DateField()
    metric = models.CharField(max_length=32)
    value = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("creator daily stat")
        constraints = [
            models.UniqueConstraint(fields=["profile", "date", "metric"], name="univ_crt_stat_unique"),
        ]
        indexes = [models.Index(fields=["profile", "metric", "date"], name="univ_crt_stat_series")]

    def __str__(self) -> str:
        return f"{self.profile_id} {self.date} {self.metric}={self.value}"


class Campaign(BaseModel, SoftDeleteModel):
    owner = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="creator_campaigns")
    #: Optional sponsoring scope (an institution, community, organisation).
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    brand_name = models.CharField(max_length=120)
    title = models.CharField(max_length=160)
    brief = models.TextField()
    categories = models.ManyToManyField(CreatorCategory, blank=True, related_name="campaigns")
    status = models.CharField(max_length=16, choices=CampaignStatus.choices, default=CampaignStatus.DRAFT)
    visibility = models.CharField(max_length=16, choices=CampaignVisibility.choices, default=CampaignVisibility.PUBLIC)
    #: Maximum accepted creators (``None``: unlimited).
    slots = models.PositiveIntegerField(null=True, blank=True)
    accepted_count = models.PositiveIntegerField(default=0)
    budget_minor = models.PositiveBigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    deliverables_summary = models.TextField(blank=True)
    application_deadline = models.DateTimeField(null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    # Requirements creators must meet to apply or be invited.
    verified_only = models.BooleanField(default=False)
    min_verified_reach = models.PositiveBigIntegerField(default=0)
    disclosure_required = models.BooleanField(default=True)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("campaign")
        indexes = [
            models.Index(fields=["status", "visibility", "-published_at"], name="univ_crt_campaign_list"),
            models.Index(fields=["scope_type", "scope_id"], name="univ_crt_campaign_scope"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(slots__isnull=True) | Q(accepted_count__lte=F("slots")), name="univ_crt_within_slots"
            ),
            models.CheckConstraint(
                condition=(Q(scope_type="") & Q(scope_id="")) | (~Q(scope_type="") & ~Q(scope_id="")),
                name="univ_crt_campaign_scope_consistent",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def sponsor_scope(self) -> tuple[str, str] | None:
        return (self.scope_type, self.scope_id) if self.scope_type else None


class Participation(BaseModel):
    campaign = models.ForeignKey(Campaign, on_delete=models.CASCADE, related_name="participations")
    profile = models.ForeignKey(CreatorProfile, on_delete=models.CASCADE, related_name="participations")
    status = models.CharField(max_length=16, choices=ParticipationStatus.choices)
    pitch = models.TextField(blank=True)
    proposed_fee_minor = models.PositiveBigIntegerField(null=True, blank=True)
    agreed_fee_minor = models.PositiveBigIntegerField(null=True, blank=True)
    #: Set when the brand paid the fee (held in escrow until completion).
    fee_paid_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=64, blank=True)
    invited_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    note = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("campaign participation")
        constraints = [
            models.UniqueConstraint(fields=["campaign", "profile"], name="univ_crt_participation_unique"),
        ]
        indexes = [models.Index(fields=["campaign", "status"], name="univ_crt_participation_status")]

    def __str__(self) -> str:
        return f"{self.profile_id} in {self.campaign_id} ({self.status})"


class Deliverable(BaseModel):
    participation = models.ForeignKey(Participation, on_delete=models.CASCADE, related_name="deliverables")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=20, choices=DeliverableStatus.choices, default=DeliverableStatus.PENDING)
    submission_url = models.URLField(max_length=500, blank=True)
    submission_note = models.TextField(blank=True)
    #: The creator confirmed the content is labelled as sponsored (#ad).
    disclosure_confirmed = models.BooleanField(default=False)
    submitted_at = models.DateTimeField(null=True, blank=True)
    reviewed_at = models.DateTimeField(null=True, blank=True)
    review_note = models.CharField(max_length=1000, blank=True)

    class Meta:
        verbose_name = _("deliverable")
        ordering = ("due_at", "created_at")

    def __str__(self) -> str:
        return self.title
