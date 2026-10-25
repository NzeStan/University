"""Base models and Core's own persistence.

Abstract bases every University model builds on:

* :class:`UUIDModel` — UUID primary key; integer ids are never exposed.
* :class:`TimeStampedModel` — ``created_at`` / ``updated_at``.
* :class:`BaseModel` — both of the above.
* :class:`SoftDeleteModel` — ``deleted_at`` with managers that hide deleted rows.

Concrete Core models:

* :class:`IdempotencyRecord` — replay protection for unsafe API requests.
* :class:`WebhookEvent` — replay protection and logging for inbound webhooks.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.ids import new_uuid


class UUIDModel(models.Model):
    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)

    class Meta:
        abstract = True


class TimeStampedModel(models.Model):
    created_at = models.DateTimeField(_("created at"), default=timezone.now, editable=False)
    updated_at = models.DateTimeField(_("updated at"), auto_now=True)

    class Meta:
        abstract = True


class BaseModel(UUIDModel, TimeStampedModel):
    class Meta:
        abstract = True


# ------------------------------------------------------------- soft delete
class SoftDeleteQuerySet(models.QuerySet):
    def delete(self) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        """Soft-delete every row in the queryset."""
        count = self.update(deleted_at=timezone.now())
        return count, {self.model._meta.label: count}

    def hard_delete(self) -> tuple[int, dict[str, int]]:
        return super().delete()

    def alive(self) -> SoftDeleteQuerySet:
        return self.filter(deleted_at__isnull=True)

    def deleted(self) -> SoftDeleteQuerySet:
        return self.filter(deleted_at__isnull=False)

    def restore(self) -> int:
        return self.update(deleted_at=None)


class SoftDeleteManager(models.Manager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Default manager: hides soft-deleted rows."""

    def get_queryset(self) -> SoftDeleteQuerySet:
        return super().get_queryset().filter(deleted_at__isnull=True)


class AllObjectsManager(models.Manager.from_queryset(SoftDeleteQuerySet)):  # type: ignore[misc]
    """Includes soft-deleted rows. Use deliberately (admin, retention jobs)."""


class SoftDeleteModel(models.Model):
    """Rows are hidden instead of deleted.

    ``objects`` excludes deleted rows; ``all_objects`` includes them. Related
    object access (``post.author``) uses Django's base manager and therefore
    still resolves deleted rows — preserving referential integrity — so
    selectors must filter on visibility explicitly.
    """

    deleted_at = models.DateTimeField(_("deleted at"), null=True, blank=True, editable=False)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    @property
    def is_deleted(self) -> bool:
        return self.deleted_at is not None

    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])
        return 1, {self._meta.label: 1}

    def hard_delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:
        return super().delete(using=using, keep_parents=keep_parents)

    def restore(self) -> None:
        self.deleted_at = None
        self.save(update_fields=["deleted_at"])


# ------------------------------------------------------------- idempotency
class IdempotencyRecord(BaseModel):
    """Stores the outcome of an idempotent request keyed by client key."""

    class Status(models.TextChoices):
        IN_PROGRESS = "in_progress", _("In progress")
        COMPLETED = "completed", _("Completed")

    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    scope = models.CharField(max_length=100)
    key = models.CharField(max_length=255)
    fingerprint = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.IN_PROGRESS)
    locked_until = models.DateTimeField(null=True, blank=True)
    response_status = models.PositiveSmallIntegerField(null=True, blank=True)
    response_body = models.JSONField(null=True, blank=True)

    class Meta:
        verbose_name = _("idempotency record")
        constraints = [
            models.UniqueConstraint(fields=["user", "scope", "key"], name="university_core_idempotency_unique")
        ]
        indexes = [models.Index(fields=["created_at"], name="university_core_idem_created")]

    def __str__(self) -> str:
        return f"{self.scope}:{self.key}"


# ---------------------------------------------------------------- webhooks
class WebhookEvent(BaseModel):
    """An inbound webhook delivery, unique per (provider, external id)."""

    class Status(models.TextChoices):
        RECEIVED = "received", _("Received")
        PROCESSED = "processed", _("Processed")
        FAILED = "failed", _("Failed")

    provider = models.CharField(max_length=64)
    external_id = models.CharField(max_length=255)
    event_type = models.CharField(max_length=128, blank=True)
    payload_sha256 = models.CharField(max_length=64)
    payload = models.JSONField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.RECEIVED)
    attempts = models.PositiveIntegerField(default=1)
    processed_at = models.DateTimeField(null=True, blank=True)
    error = models.TextField(blank=True)

    class Meta:
        verbose_name = _("webhook event")
        constraints = [
            models.UniqueConstraint(fields=["provider", "external_id"], name="university_core_webhook_unique")
        ]
        indexes = [
            models.Index(fields=["provider", "status"], name="university_core_wh_status"),
            models.Index(fields=["created_at"], name="university_core_wh_created"),
        ]

    def __str__(self) -> str:
        return f"{self.provider}:{self.external_id}"
