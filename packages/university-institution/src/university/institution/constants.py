from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class InstitutionStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    INACTIVE = "inactive", _("Inactive")


class MembershipStatus(models.TextChoices):
    PENDING = "pending", _("Pending verification")
    VERIFIED = "verified", _("Verified")
    REJECTED = "rejected", _("Rejected")
    SUSPENDED = "suspended", _("Suspended")
    REVOKED = "revoked", _("Revoked")
    LEFT = "left", _("Left")


#: Memberships that occupy the (user, institution, role) slot.
OPEN_MEMBERSHIP_STATUSES = (MembershipStatus.PENDING, MembershipStatus.VERIFIED, MembershipStatus.SUSPENDED)


class VerificationStatus(models.TextChoices):
    PENDING_REVIEW = "pending_review", _("Pending review")
    AWAITING_USER = "awaiting_user", _("Awaiting user action")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    EXPIRED = "expired", _("Expired")
    CANCELLED = "cancelled", _("Cancelled")


OPEN_VERIFICATION_STATUSES = (VerificationStatus.PENDING_REVIEW, VerificationStatus.AWAITING_USER)

INSTITUTION_SCOPE = "institution"
CAMPUS_SCOPE = "campus"


class AnnouncementStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PUBLISHED = "published", _("Published")
    ARCHIVED = "archived", _("Archived")


class AnnouncementAudience(models.TextChoices):
    PUBLIC = "public", _("Everyone")
    MEMBERS = "members", _("Verified members")


class AnnouncementPriority(models.TextChoices):
    NORMAL = "normal", _("Normal")
    IMPORTANT = "important", _("Important")
    URGENT = "urgent", _("Urgent")


ANNOUNCEMENT_CATEGORIES = ["general", "academic", "exams", "admissions", "events", "welfare", "security", "emergency"]
