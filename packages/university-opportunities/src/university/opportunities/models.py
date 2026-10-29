from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.core.storage import private_storage
from university.core.uploads import uuid_upload_to
from university.opportunities.constants import (
    ApplicationStatus,
    ApplyMethod,
    OpportunityAudience,
    OpportunityKind,
    OpportunityStatus,
    PayPeriod,
    WorkMode,
)


class Opportunity(BaseModel, SoftDeleteModel):
    poster = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opportunities_posted")
    kind = models.CharField(max_length=16, choices=OpportunityKind.choices)
    title = models.CharField(max_length=200)
    organization_name = models.CharField(max_length=200)
    organization_url = models.URLField(blank=True)
    description = models.TextField()
    location = models.CharField(max_length=120, blank=True)
    work_mode = models.CharField(max_length=16, choices=WorkMode.choices, default=WorkMode.ON_SITE)
    pay_min_minor = models.PositiveBigIntegerField(null=True, blank=True)
    pay_max_minor = models.PositiveBigIntegerField(null=True, blank=True)
    currency = models.CharField(max_length=3, default="NGN")
    pay_period = models.CharField(max_length=16, choices=PayPeriod.choices, default=PayPeriod.MONTH)
    deadline = models.DateTimeField(null=True, blank=True)
    starts_on = models.DateField(null=True, blank=True)
    apply_method = models.CharField(max_length=16, choices=ApplyMethod.choices, default=ApplyMethod.IN_APP)
    apply_url = models.URLField(blank=True)
    apply_email = models.EmailField(blank=True)
    audience = models.CharField(max_length=16, choices=OpportunityAudience.choices, default=OpportunityAudience.PUBLIC)
    scope_id = models.CharField(max_length=64, blank=True, help_text=_("Institution id for institution-only postings."))
    tags = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=OpportunityStatus.choices, default=OpportunityStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    closed_at = models.DateTimeField(null=True, blank=True)
    #: "Verified employer": granted only by staff holding ``opportunities.verify``.
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    is_hidden = models.BooleanField(default=False)
    moderation_reason = models.CharField(max_length=255, blank=True)
    applications_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("opportunity")
        verbose_name_plural = _("opportunities")
        indexes = [
            models.Index(fields=["status", "is_hidden", "-published_at"], name="univ_opp_discovery"),
            models.Index(fields=["poster", "-created_at"], name="univ_opp_poster"),
            models.Index(fields=["deadline"], name="univ_opp_deadline"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(pay_min_minor__isnull=True)
                | Q(pay_max_minor__isnull=True)
                | Q(pay_max_minor__gte=models.F("pay_min_minor")),
                name="univ_opp_pay_range",
            )
        ]

    def __str__(self) -> str:
        return f"{self.title} at {self.organization_name}"


class Application(BaseModel):
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="applications")
    applicant = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="opportunity_applications"
    )
    cover_note = models.TextField(blank=True)
    contact_email = models.EmailField()
    resume = models.FileField(
        upload_to=uuid_upload_to("opportunities/resumes"), storage=private_storage, blank=True, max_length=255
    )
    status = models.CharField(max_length=16, choices=ApplicationStatus.choices, default=ApplicationStatus.SUBMITTED)
    decided_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("application")
        constraints = [models.UniqueConstraint(fields=["opportunity", "applicant"], name="univ_opp_one_application")]
        indexes = [models.Index(fields=["applicant", "-created_at"], name="univ_opp_app_applicant")]

    def __str__(self) -> str:
        return f"Application {self.pk}"


class SavedOpportunity(BaseModel):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    opportunity = models.ForeignKey(Opportunity, on_delete=models.CASCADE, related_name="+")

    class Meta:
        verbose_name = _("saved opportunity")
        constraints = [models.UniqueConstraint(fields=["user", "opportunity"], name="univ_opp_saved_unique")]

    def __str__(self) -> str:
        return f"Saved {self.opportunity_id}"
