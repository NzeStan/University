"""Security persistence. No secret is ever stored in plaintext.

Refresh tokens, API keys and one-time codes are stored as keyed hashes
(HMAC-SHA256); login identifiers in attempt logs are hashed too.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel


class UserSessionQuerySet(models.QuerySet):
    def active(self) -> UserSessionQuerySet:
        return self.filter(revoked_at__isnull=True, expires_at__gt=timezone.now())


class UserSession(BaseModel):
    """A signed-in device. Access and refresh tokens are bound to a session."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="auth_sessions")
    auth_method = models.CharField(max_length=64, default="password")
    device_id = models.CharField(max_length=128, blank=True)
    device_name = models.CharField(max_length=100, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_ip_address = models.GenericIPAddressField(null=True, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    expires_at = models.DateTimeField()
    #: Snapshot of the user's security stamp; a mismatch invalidates the session.
    security_stamp = models.CharField(max_length=64)
    risk_reasons = models.JSONField(default=list, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_reason = models.CharField(max_length=64, blank=True)

    objects = UserSessionQuerySet.as_manager()

    class Meta:
        verbose_name = _("user session")
        indexes = [
            models.Index(fields=["user", "revoked_at", "-created_at"], name="univ_sec_session_user"),
            models.Index(fields=["expires_at"], name="univ_sec_session_expires"),
        ]

    def __str__(self) -> str:
        return f"Session {self.pk} ({self.device_name or self.auth_method})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and self.expires_at > timezone.now()


class RefreshToken(BaseModel):
    session = models.ForeignKey(UserSession, on_delete=models.CASCADE, related_name="refresh_tokens")
    token_hash = models.CharField(max_length=64, unique=True)
    expires_at = models.DateTimeField()
    used_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("refresh token")
        indexes = [models.Index(fields=["session", "used_at"], name="univ_sec_refresh_session")]

    def __str__(self) -> str:
        return f"Refresh token {self.pk}"


class APIKey(BaseModel):
    """Long-lived credential for trusted integrations.

    The full key (``<prefix>_<lookup>_<secret>``) is shown once at creation.
    ``scopes`` lists the permission codes/patterns the key may exercise; the
    key can never exceed its owner's own permissions.
    """

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="api_keys")
    name = models.CharField(max_length=100)
    lookup = models.CharField(max_length=16, unique=True)
    key_hash = models.CharField(max_length=64)
    scopes = models.JSONField(default=list, blank=True)
    allowed_ips = models.JSONField(default=list, blank=True, help_text=_("CIDR ranges; empty allows any."))
    last_used_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("API key")
        indexes = [models.Index(fields=["user", "revoked_at"], name="univ_sec_apikey_user")]

    def __str__(self) -> str:
        return f"{self.name} ({self.lookup})"

    @property
    def is_active(self) -> bool:
        return self.revoked_at is None and (self.expires_at is None or self.expires_at > timezone.now())


class LoginAttempt(BaseModel):
    """Forensic record of login attempts. Identifiers are stored hashed."""

    identifier_hash = models.CharField(max_length=64)
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    successful = models.BooleanField(default=False)
    failure_reason = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = _("login attempt")
        indexes = [
            models.Index(fields=["identifier_hash", "-created_at"], name="univ_sec_attempt_ident"),
            models.Index(fields=["ip_address", "-created_at"], name="univ_sec_attempt_ip"),
            models.Index(fields=["user", "-created_at"], name="univ_sec_attempt_user"),
        ]

    def __str__(self) -> str:
        return f"{'success' if self.successful else 'failure'} at {self.created_at:%Y-%m-%d %H:%M}"


class OTPChallenge(BaseModel):
    """A one-time code sent to an email address or phone number."""

    class Channel(models.TextChoices):
        EMAIL = "email", _("Email")
        SMS = "sms", _("SMS")

    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.CASCADE, related_name="otp_challenges"
    )
    purpose = models.CharField(max_length=32)
    channel = models.CharField(max_length=8, choices=Channel.choices)
    destination_hash = models.CharField(max_length=64)
    destination_masked = models.CharField(max_length=64, blank=True)
    code_hash = models.CharField(max_length=64)
    expires_at = models.DateTimeField()
    attempts = models.PositiveSmallIntegerField(default=0)
    max_attempts = models.PositiveSmallIntegerField(default=5)
    consumed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("one-time code challenge")
        indexes = [
            models.Index(fields=["purpose", "destination_hash", "-created_at"], name="univ_sec_otp_dest"),
            models.Index(fields=["expires_at"], name="univ_sec_otp_expires"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(attempts__lte=models.F("max_attempts")), name="univ_sec_otp_attempts")
        ]

    def __str__(self) -> str:
        return f"{self.purpose} via {self.channel}"


class ExternalIdentity(BaseModel):
    """Link between a user and an external identity provider account."""

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="external_identities")
    provider = models.CharField(max_length=64)
    subject = models.CharField(max_length=255)
    email = models.EmailField(blank=True)
    last_login_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("external identity")
        verbose_name_plural = _("external identities")
        constraints = [
            models.UniqueConstraint(fields=["provider", "subject"], name="univ_sec_external_identity_unique"),
            models.UniqueConstraint(fields=["user", "provider"], name="univ_sec_external_identity_user_provider"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.subject}"
