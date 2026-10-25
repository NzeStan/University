"""Moderation data model.

::

    ReportReason            configurable reasons with severities
    ModerationCase ──┬── CaseScope          scope + ancestors, for scoped queues
                     ├── Report             one per reporter per case
                     └── ModerationAction ── ModerationAppeal (one per action)
    UserRestriction         time-boxed content-creation sanctions
    ModerationRule          automated, explainable rules

Content is referenced as ``(content_type, object_id)`` and resolved through
Core content adapters — no generic foreign keys, no imports of content
modules. For anonymous content ``target_author`` is never stored on the case.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel
from university.moderation.constants import (
    Action,
    AppealStatus,
    CaseSource,
    CaseStatus,
    RestrictionKind,
    RuleType,
    Severity,
)

USER = settings.AUTH_USER_MODEL


class ReportReason(BaseModel):
    key = models.SlugField(max_length=50, unique=True)
    label = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    severity = models.CharField(max_length=16, choices=Severity.choices, default=Severity.LOW)
    requires_details = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)
    ordering = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("report reason")
        ordering = ("ordering", "label")

    def __str__(self) -> str:
        return self.label


class ModerationCase(BaseModel):
    content_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=CaseStatus.choices, default=CaseStatus.OPEN)
    source = models.CharField(max_length=16, choices=CaseSource.choices, default=CaseSource.REPORT)
    priority = models.PositiveIntegerField(default=0)
    max_severity_weight = models.PositiveSmallIntegerField(default=0)
    report_count = models.PositiveIntegerField(default=0)
    #: Author of the content — always NULL for anonymous content.
    target_author = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    target_is_anonymous = models.BooleanField(default=False)
    #: Evidence snapshot taken when the case opened (purged with the case).
    excerpt = models.TextField(blank=True)
    auto_actioned = models.BooleanField(default=False)
    assigned_to = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolved_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    resolution = models.CharField(max_length=16, blank=True)

    class Meta:
        verbose_name = _("moderation case")
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id"],
                condition=Q(status=CaseStatus.OPEN),
                name="univ_mod_case_one_open",
            )
        ]
        indexes = [
            models.Index(fields=["status", "-priority", "created_at"], name="univ_mod_case_queue"),
            models.Index(fields=["content_type", "object_id"], name="univ_mod_case_target"),
        ]

    def __str__(self) -> str:
        return f"{self.content_type}:{self.object_id} ({self.status})"

    @property
    def scope(self) -> tuple[str, str] | None:
        return (self.scope_type, self.scope_id) if self.scope_type else None


class CaseScope(models.Model):
    """The case's scope and every ancestor scope (campus → institution …)."""

    case = models.ForeignKey(ModerationCase, on_delete=models.CASCADE, related_name="scopes")
    scope_type = models.CharField(max_length=32)
    scope_id = models.CharField(max_length=64)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["case", "scope_type", "scope_id"], name="univ_mod_case_scope_unique")
        ]
        indexes = [models.Index(fields=["scope_type", "scope_id"], name="univ_mod_case_scope_lookup")]

    def __str__(self) -> str:
        return f"{self.scope_type}:{self.scope_id}"


class Report(BaseModel):
    case = models.ForeignKey(ModerationCase, on_delete=models.CASCADE, related_name="reports")
    reporter = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="moderation_reports")
    reason = models.ForeignKey(ReportReason, on_delete=models.PROTECT, related_name="reports")
    details = models.TextField(blank=True)

    class Meta:
        verbose_name = _("report")
        constraints = [models.UniqueConstraint(fields=["case", "reporter"], name="univ_mod_report_once")]
        indexes = [models.Index(fields=["reporter", "-created_at"], name="univ_mod_report_reporter")]

    def __str__(self) -> str:
        return f"Report {self.pk}"


class ModerationRule(BaseModel):
    key = models.SlugField(max_length=64, unique=True)
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    rule_type = models.CharField(max_length=32, choices=RuleType.choices)
    params = models.JSONField(default=dict, blank=True)
    action = models.CharField(max_length=16, choices=Action.choices, default=Action.HIDE)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("moderation rule")

    def __str__(self) -> str:
        return self.name


class ModerationAction(BaseModel):
    """An action taken by a moderator or an automated rule. Never deleted;
    reversals are recorded in place."""

    case = models.ForeignKey(ModerationCase, null=True, blank=True, on_delete=models.SET_NULL, related_name="actions")
    action = models.CharField(max_length=16, choices=Action.choices)
    content_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    #: The affected user. NULL for content-level actions on anonymous content.
    target_user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    automated = models.BooleanField(default=False)
    rule = models.ForeignKey(ModerationRule, null=True, blank=True, on_delete=models.SET_NULL, related_name="actions")
    reason = models.CharField(max_length=500, blank=True)
    #: Machine-readable explanation (rule, inputs, thresholds) for automated actions.
    explanation = models.JSONField(default=dict, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    reversed_at = models.DateTimeField(null=True, blank=True)
    reversed_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reversal_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("moderation action")
        indexes = [
            models.Index(fields=["target_user", "-created_at"], name="univ_mod_action_user"),
            models.Index(fields=["content_type", "object_id", "-created_at"], name="univ_mod_action_target"),
        ]

    def __str__(self) -> str:
        return f"{self.action} on {self.content_type}:{self.object_id}"


class UserRestriction(BaseModel):
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="moderation_restrictions")
    kind = models.CharField(max_length=16, choices=RestrictionKind.choices, default=RestrictionKind.POSTING)
    ends_at = models.DateTimeField()
    lifted_at = models.DateTimeField(null=True, blank=True)
    action = models.ForeignKey(ModerationAction, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reason = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("user restriction")
        indexes = [models.Index(fields=["user", "ends_at"], name="univ_mod_restriction_user")]

    def __str__(self) -> str:
        return f"{self.kind} until {self.ends_at:%Y-%m-%d}"


class ModerationAppeal(BaseModel):
    action = models.OneToOneField(ModerationAction, on_delete=models.CASCADE, related_name="appeal")
    appellant = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="moderation_appeals")
    statement = models.TextField()
    status = models.CharField(max_length=16, choices=AppealStatus.choices, default=AppealStatus.PENDING)
    decided_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    decided_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        verbose_name = _("moderation appeal")
        indexes = [models.Index(fields=["status", "created_at"], name="univ_mod_appeal_queue")]

    def __str__(self) -> str:
        return f"Appeal {self.pk} ({self.status})"
