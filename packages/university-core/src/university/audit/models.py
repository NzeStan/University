"""Audit log persistence.

Audit entries are **append-only**: the model refuses updates and deletes, and
its queryset refuses bulk ``update()``/``delete()``. Only the retention job
removes expired entries, through an explicit private path. Each entry stores
an HMAC over its content (``entry_hash``) so modification is detectable
(``manage.py university_verify_audit``); with ``AUDIT.HASH_CHAIN`` each entry
also commits to its predecessor so deletions are detectable too.

For stronger guarantees, grant the application's database role only
``INSERT``/``SELECT`` on this table and stream entries to a WORM sink.
"""

from __future__ import annotations

from typing import Any

from django.conf import settings
from django.db import models
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.ids import new_uuid


class AuditLogImmutableError(Exception):
    """Raised on any attempt to modify or delete an audit entry."""


class AuditLogQuerySet(models.QuerySet):
    def update(self, **kwargs: Any) -> int:
        raise AuditLogImmutableError("Audit log entries cannot be updated.")

    def delete(self) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        raise AuditLogImmutableError("Audit log entries cannot be deleted.")

    def _purge(self) -> int:
        """Retention-only deletion path. Do not call from application code."""
        deleted, _ = models.QuerySet.delete(self)
        return deleted


class AuditLog(models.Model):
    class Outcome(models.TextChoices):
        SUCCESS = "success", _("Success")
        FAILURE = "failure", _("Failure")
        DENIED = "denied", _("Denied")

    id = models.UUIDField(primary_key=True, default=new_uuid, editable=False)
    created_at = models.DateTimeField(default=timezone.now, editable=False)
    action = models.CharField(max_length=100)
    category = models.CharField(max_length=32)
    outcome = models.CharField(max_length=16, choices=Outcome.choices, default=Outcome.SUCCESS)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="+",
    )
    #: Stable actor reference that survives account purging.
    actor_ref = models.CharField(max_length=64, blank=True)
    target_type = models.CharField(max_length=100, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.CharField(max_length=512, blank=True)
    request_id = models.CharField(max_length=128, blank=True)
    metadata = models.JSONField(default=dict, blank=True)
    previous_hash = models.CharField(max_length=64, blank=True)
    entry_hash = models.CharField(max_length=64, editable=False)

    objects = AuditLogQuerySet.as_manager()

    class Meta:
        verbose_name = _("audit log entry")
        verbose_name_plural = _("audit log")
        ordering = ("-created_at",)
        default_permissions = ("view",)
        indexes = [
            models.Index(fields=["-created_at"], name="univ_audit_created"),
            models.Index(fields=["actor", "-created_at"], name="univ_audit_actor"),
            models.Index(fields=["category", "-created_at"], name="univ_audit_category"),
            models.Index(fields=["action", "-created_at"], name="univ_audit_action"),
            models.Index(fields=["target_type", "target_id"], name="univ_audit_target"),
            models.Index(fields=["scope_type", "scope_id", "-created_at"], name="univ_audit_scope"),
        ]

    def __str__(self) -> str:
        return f"{self.created_at:%Y-%m-%d %H:%M:%S} {self.action} ({self.outcome})"

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AuditLogImmutableError("Audit log entries cannot be updated.")
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any) -> tuple[int, dict[str, int]]:
        raise AuditLogImmutableError("Audit log entries cannot be deleted.")

    def hashable_content(self) -> dict[str, Any]:
        return {
            "id": str(self.id),
            "created_at": self.created_at.isoformat(),
            "action": self.action,
            "category": self.category,
            "outcome": self.outcome,
            "actor_ref": self.actor_ref,
            "target_type": self.target_type,
            "target_id": self.target_id,
            "scope_type": self.scope_type,
            "scope_id": self.scope_id,
            "ip_address": self.ip_address or "",
            "user_agent": self.user_agent,
            "request_id": self.request_id,
            "metadata": self.metadata,
            "previous_hash": self.previous_hash,
        }


class AuditChainHead(models.Model):
    """Single-row pointer to the latest entry hash (used when chaining)."""

    id = models.PositiveSmallIntegerField(primary_key=True, default=1)
    last_hash = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("audit chain head")
        default_permissions = ()

    def __str__(self) -> str:
        return self.last_hash or "(empty)"


#: Module-level alias of the outcome choices (importable by dotted path, e.g. for OpenAPI enum naming).
AuditOutcomeChoices = AuditLog.Outcome
