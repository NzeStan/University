"""Enumerations shared by the users app and its consumers (no model imports)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class UserStatus(models.TextChoices):
    #: Registered; waiting for email verification ("verify_first" mode).
    PENDING = "pending", _("Pending verification")
    ACTIVE = "active", _("Active")
    #: Deactivated (by the user or an administrator); can be reactivated.
    INACTIVE = "inactive", _("Inactive")
    #: Temporarily blocked, optionally until ``suspended_until``.
    SUSPENDED = "suspended", _("Suspended")
    BANNED = "banned", _("Banned")
    #: Soft-deleted; anonymised after the deletion grace period.
    DELETED = "deleted", _("Deleted")


class ProfileVisibility(models.TextChoices):
    PUBLIC = "public", _("Everyone")
    MEMBERS = "members", _("Signed-in members")
    PRIVATE = "private", _("Only me")


class DigestFrequency(models.TextChoices):
    NEVER = "never", _("Never")
    DAILY = "daily", _("Daily")
    WEEKLY = "weekly", _("Weekly")


class MFAChannel(models.TextChoices):
    EMAIL = "email", _("Email")
    SMS = "sms", _("SMS")


class RegistrationMode:
    VERIFY_FIRST = "verify_first"
    OPEN = "open"


#: Statuses that can never authenticate.
NON_AUTHENTICATING_STATUSES = frozenset(
    {UserStatus.PENDING, UserStatus.INACTIVE, UserStatus.SUSPENDED, UserStatus.BANNED, UserStatus.DELETED}
)
