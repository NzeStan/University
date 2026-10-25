"""The University user model and per-user preferences.

``AbstractUniversityUser`` is the extension point: projects that need extra
user columns subclass it in their own app and point ``AUTH_USER_MODEL`` at the
subclass. The concrete :class:`User` is swappable exactly like Django's own,
so it is not created when another model is configured. Prefer one-to-one
profile models for module-specific data over widening the user table.

Design notes:

* UUID primary key; integer ids never exist.
* ``email`` is the login identifier, stored lowercase and unique.
* ``handle`` is the optional public username (unique, lowercase).
* ``phone_number`` is only unique once verified, so an unverified claim on a
  number cannot block its real owner.
* ``status`` drives ``is_active``; they cannot drift apart.
* ``security_stamp`` rotates on credential changes and instantly invalidates
  every access token and session issued before the change.
* Deletion is soft (``status=deleted`` + ``deleted_at``); personal data is
  anonymised after a configurable grace period.
"""

from __future__ import annotations

import secrets
from typing import Any

from django.conf import settings
from django.contrib.auth.base_user import AbstractBaseUser
from django.contrib.auth.models import PermissionsMixin
from django.db import models
from django.db.models import Q
from django.utils import timezone as dj_timezone
from django.utils.translation import gettext_lazy as _

from university.core.ids import new_uuid
from university.core.models import BaseModel
from university.users.constants import (
    DigestFrequency,
    MFAChannel,
    ProfileVisibility,
    UserStatus,
)
from university.users.managers import UserManager
from university.users.validators import (
    normalize_email,
    normalize_handle,
    validate_handle,
    validate_phone,
)


def generate_security_stamp() -> str:
    return secrets.token_hex(16)


class AbstractUniversityUser(AbstractBaseUser, PermissionsMixin):
    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    email = models.EmailField(_("email address"), max_length=254, unique=True)
    pending_email = models.EmailField(_("pending email address"), max_length=254, blank=True)
    handle = models.CharField(
        _("handle"),
        max_length=30,
        unique=True,
        null=True,
        blank=True,
        validators=[validate_handle],
        help_text=_("Optional public username."),
    )
    display_name = models.CharField(_("display name"), max_length=100, blank=True)
    phone_number = models.CharField(
        _("phone number"), max_length=16, null=True, blank=True, validators=[validate_phone]
    )
    email_verified_at = models.DateTimeField(null=True, blank=True)
    phone_verified_at = models.DateTimeField(null=True, blank=True)

    status = models.CharField(max_length=16, choices=UserStatus.choices, default=UserStatus.ACTIVE)
    status_reason = models.CharField(max_length=255, blank=True)
    status_changed_at = models.DateTimeField(null=True, blank=True)
    suspended_until = models.DateTimeField(null=True, blank=True)

    is_staff = models.BooleanField(_("staff status"), default=False, help_text=_("Can log into the admin site."))
    #: Derived from ``status`` on every save — do not set directly.
    is_active = models.BooleanField(_("active"), default=True, editable=False)

    security_stamp = models.CharField(max_length=64, default=generate_security_stamp, editable=False)
    password_changed_at = models.DateTimeField(null=True, blank=True)
    locale = models.CharField(max_length=16, blank=True, help_text=_("BCP 47 tag, e.g. en-NG."))
    timezone = models.CharField(max_length=64, blank=True, help_text=_("IANA zone, e.g. Africa/Lagos."))

    created_at = models.DateTimeField(_("date joined"), default=dj_timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)
    anonymized_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = UserManager()
    all_objects = UserManager(include_deleted=True)

    USERNAME_FIELD = "email"
    EMAIL_FIELD = "email"
    REQUIRED_FIELDS: list[str] = []

    class Meta:
        abstract = True
        verbose_name = _("user")
        verbose_name_plural = _("users")
        constraints = [
            models.UniqueConstraint(
                fields=["phone_number"],
                condition=Q(phone_verified_at__isnull=False) & Q(phone_number__isnull=False),
                name="%(app_label)s_%(class)s_verified_phone_unique",
            ),
        ]
        indexes = [
            models.Index(fields=["status"], name="%(app_label)s_%(class)s_status"),
            models.Index(fields=["created_at"], name="%(app_label)s_%(class)s_created"),
            models.Index(fields=["phone_number"], name="%(app_label)s_%(class)s_phone"),
        ]

    def __str__(self) -> str:
        return self.handle or self.email

    # -- invariants -------------------------------------------------------
    def clean(self) -> None:
        super().clean()
        self.email = normalize_email(self.email)
        self.handle = normalize_handle(self.handle)

    def save(self, *args: Any, **kwargs: Any) -> None:
        self.email = normalize_email(self.email)
        self.handle = normalize_handle(self.handle)
        self.is_active = self.status == UserStatus.ACTIVE
        update_fields = kwargs.get("update_fields")
        if update_fields is not None and "status" in update_fields:
            kwargs["update_fields"] = {*update_fields, "is_active"}
        super().save(*args, **kwargs)

    def set_password(self, raw_password: str | None) -> None:
        super().set_password(raw_password)
        self.password_changed_at = dj_timezone.now()

    def rotate_security_stamp(self) -> None:
        self.security_stamp = generate_security_stamp()

    # -- convenience ------------------------------------------------------
    @property
    def email_verified(self) -> bool:
        return self.email_verified_at is not None

    @property
    def phone_verified(self) -> bool:
        return self.phone_verified_at is not None

    @property
    def is_deleted(self) -> bool:
        return self.status == UserStatus.DELETED

    def get_full_name(self) -> str:
        return self.display_name or self.handle or ""

    def get_short_name(self) -> str:
        return self.display_name or self.handle or ""


class User(AbstractUniversityUser):
    class Meta(AbstractUniversityUser.Meta):
        swappable = "AUTH_USER_MODEL"


# ----------------------------------------------------------- preferences
class PrivacySettings(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="privacy_settings")
    profile_visibility = models.CharField(
        max_length=16, choices=ProfileVisibility.choices, default=ProfileVisibility.PUBLIC
    )
    show_email = models.BooleanField(default=False)
    show_phone = models.BooleanField(default=False)
    show_affiliations = models.BooleanField(
        default=True, help_text=_("Show institution/community memberships on the profile.")
    )
    discoverable_by_email = models.BooleanField(default=False)
    discoverable_by_phone = models.BooleanField(default=False)
    searchable = models.BooleanField(default=True, help_text=_("Include the profile in search results."))
    #: Module-contributed privacy preferences, namespaced by module name.
    extra = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("privacy settings")
        verbose_name_plural = _("privacy settings")

    def __str__(self) -> str:
        return f"Privacy settings for {self.user_id}"


class NotificationSettings(BaseModel):
    user = models.OneToOneField(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notification_settings"
    )
    in_app_enabled = models.BooleanField(default=True)
    email_enabled = models.BooleanField(default=True)
    push_enabled = models.BooleanField(default=True)
    sms_enabled = models.BooleanField(default=False)
    marketing_emails = models.BooleanField(default=False)
    digest_frequency = models.CharField(max_length=16, choices=DigestFrequency.choices, default=DigestFrequency.WEEKLY)
    quiet_hours_start = models.TimeField(null=True, blank=True)
    quiet_hours_end = models.TimeField(null=True, blank=True)
    #: ``{category: {channel: bool}}`` overrides, e.g. ``{"mentions": {"email": false}}``.
    categories = models.JSONField(default=dict, blank=True)

    class Meta:
        verbose_name = _("notification settings")
        verbose_name_plural = _("notification settings")

    def __str__(self) -> str:
        return f"Notification settings for {self.user_id}"

    def allows(self, category: str, channel: str) -> bool:
        if not getattr(self, f"{channel}_enabled", True):
            return False
        return bool((self.categories or {}).get(category, {}).get(channel, True))


class SecuritySettings(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="security_settings")
    login_alerts_enabled = models.BooleanField(default=True)
    mfa_enabled = models.BooleanField(default=False)
    mfa_channel = models.CharField(max_length=16, choices=MFAChannel.choices, default=MFAChannel.EMAIL)
    mfa_enabled_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("security settings")
        verbose_name_plural = _("security settings")

    def __str__(self) -> str:
        return f"Security settings for {self.user_id}"


class ConsentRecord(BaseModel):
    """Append-only history of consent decisions (lawful-basis evidence)."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="consents")
    purpose = models.CharField(max_length=64)
    version = models.CharField(max_length=32, blank=True)
    granted = models.BooleanField()
    source = models.CharField(max_length=32, default="api")
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        verbose_name = _("consent record")
        ordering = ("-created_at",)
        indexes = [models.Index(fields=["user", "purpose", "-created_at"], name="univ_users_consent_lookup")]

    def __str__(self) -> str:
        return f"{self.purpose}={'granted' if self.granted else 'withdrawn'}"
