"""Institution data model.

Structure::

    InstitutionType            (configurable: university, polytechnic, …)
    Institution ──┬── InstitutionDomain   (email domains used for verification)
                  ├── Campus
                  ├── AcademicUnit (tree: college/faculty/school/department …)
                  ├── Programme ── Level
                  ├── AcademicSession ── Semester
                  └── InstitutionMembership ── VerificationRequest

An institution is a logical tenant boundary: permissions, moderation and
visibility can be scoped to it. A user may hold memberships in several
institutions (configurable).
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator, RegexValidator
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.core.storage import private_storage
from university.core.uploads import uuid_upload_to
from university.institution.constants import (
    OPEN_MEMBERSHIP_STATUSES,
    OPEN_VERIFICATION_STATUSES,
    InstitutionStatus,
    MembershipStatus,
    VerificationStatus,
)

country_code_validator = RegexValidator(r"^[A-Z]{2}$", _("Use an ISO 3166-1 alpha-2 country code, e.g. NG."))
domain_validator = RegexValidator(
    r"^(?=.{4,253}$)([a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+[a-z]{2,63}$", _("Enter a valid domain name.")
)
year_validators = [MinValueValidator(1800), MaxValueValidator(2200)]


class InstitutionType(BaseModel):
    key = models.SlugField(max_length=50, unique=True)
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True)
    is_active = models.BooleanField(default=True)
    ordering = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("institution type")
        ordering = ("ordering", "name")

    def __str__(self) -> str:
        return self.name


class Institution(BaseModel, SoftDeleteModel):
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True)
    slug = models.SlugField(max_length=100, unique=True)
    type = models.ForeignKey(InstitutionType, on_delete=models.PROTECT, related_name="institutions")
    ownership = models.CharField(max_length=32, blank=True)
    country = models.CharField(max_length=2, validators=[country_code_validator], db_index=True)
    region = models.CharField(_("state / region"), max_length=100, blank=True)
    city = models.CharField(max_length=100, blank=True)
    website = models.URLField(blank=True)
    description = models.TextField(blank=True)
    founded_year = models.PositiveSmallIntegerField(null=True, blank=True, validators=year_validators)
    status = models.CharField(max_length=16, choices=InstitutionStatus.choices, default=InstitutionStatus.ACTIVE)
    is_verified = models.BooleanField(default=False, help_text=_("Confirmed as a genuine institution."))
    #: Verification method keys offered to members; empty -> deployment default.
    verification_methods = models.JSONField(default=list, blank=True)
    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("institution")
        ordering = ("name",)
        indexes = [
            models.Index(fields=["country", "status"], name="univ_inst_country_status"),
            models.Index(fields=["type", "status"], name="univ_inst_type_status"),
            models.Index(fields=["name"], name="univ_inst_name"),
        ]

    def __str__(self) -> str:
        return self.short_name or self.name


class InstitutionDomain(BaseModel):
    """An email domain owned by an institution (``unilag.edu.ng``)."""

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="domains")
    domain = models.CharField(max_length=253, unique=True, validators=[domain_validator])
    allow_subdomains = models.BooleanField(default=False, help_text=_("Also accept e.g. student.<domain>."))
    is_verified = models.BooleanField(default=False, help_text=_("Only verified domains can verify members."))

    class Meta:
        verbose_name = _("institution email domain")
        ordering = ("domain",)

    def __str__(self) -> str:
        return self.domain

    def matches(self, email_domain: str) -> bool:
        email_domain = email_domain.lower()
        return email_domain == self.domain or (self.allow_subdomains and email_domain.endswith("." + self.domain))


class Campus(BaseModel):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="campuses")
    name = models.CharField(max_length=255)
    slug = models.SlugField(max_length=100)
    address = models.CharField(max_length=500, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    is_main = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("campus")
        verbose_name_plural = _("campuses")
        ordering = ("-is_main", "name")
        constraints = [
            models.UniqueConstraint(fields=["institution", "slug"], name="univ_inst_campus_slug_unique"),
            models.UniqueConstraint(
                fields=["institution"], condition=Q(is_main=True), name="univ_inst_campus_one_main"
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AcademicUnit(BaseModel):
    """A node in an institution's academic structure.

    The tree adapts to each institution: ``College > School > Department``,
    ``Faculty > Department``, or a flat list of schools are all valid.
    """

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="academic_units")
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.CASCADE, related_name="children")
    campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.SET_NULL, related_name="academic_units")
    unit_type = models.CharField(max_length=32)
    name = models.CharField(max_length=255)
    short_name = models.CharField(max_length=50, blank=True)
    code = models.CharField(max_length=32, blank=True)
    slug = models.SlugField(max_length=100)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("academic unit")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(fields=["institution", "slug"], name="univ_inst_unit_slug_unique"),
            models.CheckConstraint(condition=~Q(parent=F("id")), name="univ_inst_unit_not_own_parent"),
        ]
        indexes = [models.Index(fields=["institution", "unit_type"], name="univ_inst_unit_type")]

    def __str__(self) -> str:
        return self.name


class _UnitTypeManager(models.Manager):
    unit_type = ""

    def get_queryset(self) -> models.QuerySet:
        return super().get_queryset().filter(unit_type=self.unit_type)


def _typed_manager(unit_type: str) -> _UnitTypeManager:
    manager = _UnitTypeManager()
    manager.unit_type = unit_type
    return manager


class _FixedUnitType:
    """Proxy mixin: rows saved through the proxy get its unit type."""

    UNIT_TYPE = ""

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.unit_type = self.UNIT_TYPE
        super().save(*args, **kwargs)  # type: ignore[misc]


class College(_FixedUnitType, AcademicUnit):
    UNIT_TYPE = "college"
    objects = _typed_manager("college")

    class Meta:
        proxy = True


class Faculty(_FixedUnitType, AcademicUnit):
    UNIT_TYPE = "faculty"
    objects = _typed_manager("faculty")

    class Meta:
        proxy = True
        verbose_name_plural = _("faculties")


class School(_FixedUnitType, AcademicUnit):
    UNIT_TYPE = "school"
    objects = _typed_manager("school")

    class Meta:
        proxy = True


class Department(_FixedUnitType, AcademicUnit):
    UNIT_TYPE = "department"
    objects = _typed_manager("department")

    class Meta:
        proxy = True


class Programme(BaseModel):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="programmes")
    academic_unit = models.ForeignKey(
        AcademicUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="programmes"
    )
    name = models.CharField(max_length=255)
    code = models.CharField(max_length=32, blank=True)
    award = models.CharField(max_length=64, blank=True, help_text=_("e.g. B.Sc., HND, NCE, M.Sc."))
    qualification_level = models.CharField(max_length=32, blank=True)
    study_mode = models.CharField(max_length=32, blank=True)
    duration_years = models.DecimalField(max_digits=3, decimal_places=1, null=True, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("programme")
        ordering = ("name",)
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"], condition=~Q(code=""), name="univ_inst_programme_code_unique"
            )
        ]

    def __str__(self) -> str:
        return self.name


class Level(BaseModel):
    """A year/stage of study: ``100 Level``, ``ND1``, ``HND2``, ``Year 3``."""

    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="levels")
    programme = models.ForeignKey(Programme, null=True, blank=True, on_delete=models.CASCADE, related_name="levels")
    code = models.CharField(max_length=32)
    name = models.CharField(max_length=100)
    order = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("level")
        ordering = ("order", "code")
        constraints = [
            models.UniqueConstraint(
                fields=["institution", "code"],
                condition=Q(programme__isnull=True),
                name="univ_inst_level_code_unique",
            ),
            models.UniqueConstraint(
                fields=["institution", "programme", "code"],
                condition=Q(programme__isnull=False),
                name="univ_inst_level_programme_code_unique",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class AcademicSession(BaseModel):
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="academic_sessions")
    name = models.CharField(max_length=50, help_text=_("e.g. 2025/2026"))
    starts_on = models.DateField()
    ends_on = models.DateField()
    is_current = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("academic session")
        ordering = ("-starts_on",)
        constraints = [
            models.UniqueConstraint(fields=["institution", "name"], name="univ_inst_session_name_unique"),
            models.UniqueConstraint(
                fields=["institution"], condition=Q(is_current=True), name="univ_inst_session_one_current"
            ),
            models.CheckConstraint(condition=Q(ends_on__gt=F("starts_on")), name="univ_inst_session_dates"),
        ]

    def __str__(self) -> str:
        return self.name


class Semester(BaseModel):
    """A term within a session (semester, trimester, harmattan/rain …)."""

    session = models.ForeignKey(AcademicSession, on_delete=models.CASCADE, related_name="semesters")
    name = models.CharField(max_length=50)
    order = models.PositiveSmallIntegerField(default=1)
    starts_on = models.DateField(null=True, blank=True)
    ends_on = models.DateField(null=True, blank=True)
    is_current = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("semester")
        ordering = ("order",)
        constraints = [
            models.UniqueConstraint(fields=["session", "order"], name="univ_inst_semester_order_unique"),
            models.UniqueConstraint(
                fields=["session"], condition=Q(is_current=True), name="univ_inst_semester_one_current"
            ),
            models.CheckConstraint(
                condition=Q(starts_on__isnull=True) | Q(ends_on__isnull=True) | Q(ends_on__gt=F("starts_on")),
                name="univ_inst_semester_dates",
            ),
        ]

    def __str__(self) -> str:
        return self.name


class InstitutionMembership(BaseModel):
    """A user's affiliation with an institution in a given role.

    Student/staff identifiers are never stored in plaintext: only a keyed hash
    (to enforce one account per identifier) and a short masked hint.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="institution_memberships")
    institution = models.ForeignKey(Institution, on_delete=models.CASCADE, related_name="memberships")
    role = models.CharField(max_length=32)
    status = models.CharField(max_length=16, choices=MembershipStatus.choices, default=MembershipStatus.PENDING)
    campus = models.ForeignKey(Campus, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    academic_unit = models.ForeignKey(AcademicUnit, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    programme = models.ForeignKey(Programme, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    level = models.ForeignKey(Level, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    identifier_hash = models.CharField(max_length=64, blank=True)
    identifier_hint = models.CharField(max_length=16, blank=True)
    entry_year = models.PositiveSmallIntegerField(null=True, blank=True, validators=year_validators)
    graduation_year = models.PositiveSmallIntegerField(null=True, blank=True, validators=year_validators)
    is_primary = models.BooleanField(default=False)
    verified_at = models.DateTimeField(null=True, blank=True)
    verified_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    verification_method = models.CharField(max_length=32, blank=True)
    status_reason = models.CharField(max_length=255, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("institution membership")
        constraints = [
            models.UniqueConstraint(
                fields=["user", "institution", "role"],
                condition=Q(status__in=OPEN_MEMBERSHIP_STATUSES),
                name="univ_inst_membership_open_unique",
            ),
            models.UniqueConstraint(
                fields=["institution", "role", "identifier_hash"],
                condition=~Q(identifier_hash="") & Q(status__in=OPEN_MEMBERSHIP_STATUSES),
                name="univ_inst_membership_identifier_unique",
            ),
            models.UniqueConstraint(
                fields=["user"], condition=Q(is_primary=True), name="univ_inst_membership_one_primary"
            ),
            models.CheckConstraint(
                condition=Q(entry_year__isnull=True)
                | Q(graduation_year__isnull=True)
                | Q(graduation_year__gte=F("entry_year")),
                name="univ_inst_membership_years",
            ),
        ]
        indexes = [
            models.Index(fields=["institution", "status", "role"], name="univ_inst_member_inst"),
            models.Index(fields=["user", "status"], name="univ_inst_member_user"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} @ {self.institution_id} ({self.role}, {self.status})"


class VerificationRequest(BaseModel):
    membership = models.ForeignKey(
        InstitutionMembership, on_delete=models.CASCADE, related_name="verification_requests"
    )
    method = models.CharField(max_length=32)
    status = models.CharField(
        max_length=16, choices=VerificationStatus.choices, default=VerificationStatus.PENDING_REVIEW
    )
    #: Non-sensitive evidence summary shown to reviewers (masked values only).
    evidence = models.JSONField(default=dict, blank=True)
    #: Keyed hash of an institutional email, so one address verifies one account.
    email_hash = models.CharField(max_length=64, blank=True)
    otp_challenge_id = models.UUIDField(null=True, blank=True)
    document = models.FileField(
        upload_to=uuid_upload_to("institution/verification"), storage=private_storage, blank=True, max_length=255
    )
    expires_at = models.DateTimeField(null=True, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    decided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    decision_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("verification request")
        constraints = [
            models.UniqueConstraint(
                fields=["membership"],
                condition=Q(status__in=OPEN_VERIFICATION_STATUSES),
                name="univ_inst_verification_one_open",
            ),
            models.UniqueConstraint(
                fields=["method", "email_hash"],
                condition=~Q(email_hash="") & Q(status=VerificationStatus.APPROVED),
                name="univ_inst_verification_email_once",
            ),
        ]
        indexes = [models.Index(fields=["status", "-created_at"], name="univ_inst_verif_status")]

    def __str__(self) -> str:
        return f"{self.method} ({self.status})"
