"""Notification data model.

::

    Notification ──┬── NotificationActor (who contributed to an aggregated row)
                   └── Delivery          (one per external channel: email, push, SMS)
    PushDevice                           (provider registration tokens)

Notifications store references, never copies of content: titles are rendered
when read, from the verb, the actor's *current* name and ids in ``data``. A
renamed or purged actor, or a deleted post, is reflected immediately.

Rows that share an unread ``group_key`` aggregate ("Ada and 4 more reacted to
your post") instead of piling up.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel
from university.notifications.constants import Channel, DeliveryStatus, Platform

USER = settings.AUTH_USER_MODEL


class Notification(BaseModel):
    recipient = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="notifications")
    #: Registered verb key, e.g. ``social.mention`` (see :mod:`university.notifications.verbs`).
    verb = models.CharField(max_length=64)
    category = models.CharField(max_length=32)
    #: The most recent actor; ``None`` for system notifications.
    actor = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    actor_count = models.PositiveIntegerField(default=1)
    #: Content type (as used by Core content adapters) and id of the subject.
    target_type = models.CharField(max_length=64, blank=True)
    target_id = models.CharField(max_length=64, blank=True)
    #: Identifiers and enum values only — never content or secrets.
    data = models.JSONField(default=dict, blank=True)
    group_key = models.CharField(max_length=160, blank=True)
    #: False when the recipient turned the category's in-app channel off.
    in_app = models.BooleanField(default=True)
    #: Feed position; bumped when an aggregated notification gains an actor.
    last_activity_at = models.DateTimeField(default=timezone.now)
    seen_at = models.DateTimeField(null=True, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("notification")
        indexes = [
            models.Index(fields=["recipient", "-last_activity_at", "-id"], name="univ_notif_feed"),
            models.Index(fields=["recipient", "read_at"], name="univ_notif_unread"),
            models.Index(fields=["target_type", "target_id"], name="univ_notif_target"),
            models.Index(fields=["last_activity_at"], name="univ_notif_activity"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["recipient", "group_key"],
                condition=Q(read_at__isnull=True) & ~Q(group_key=""),
                name="univ_notif_unread_group",
            ),
        ]

    def __str__(self) -> str:
        return f"{self.verb} for {self.recipient_id}"


class NotificationActor(models.Model):
    """One row per distinct actor of a (possibly aggregated) notification."""

    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="actors")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = _("notification actor")
        constraints = [models.UniqueConstraint(fields=["notification", "user"], name="univ_notif_actor_unique")]
        indexes = [models.Index(fields=["user"], name="univ_notif_actor_user")]

    def __str__(self) -> str:
        return f"{self.user_id} on {self.notification_id}"


class Delivery(BaseModel):
    notification = models.ForeignKey(Notification, on_delete=models.CASCADE, related_name="deliveries")
    channel = models.CharField(max_length=16, choices=Channel.choices)
    status = models.CharField(max_length=16, choices=DeliveryStatus.choices, default=DeliveryStatus.PENDING)
    attempts = models.PositiveSmallIntegerField(default=0)
    #: Machine-readable reason for a skip, suppression or failure (never content).
    reason = models.CharField(max_length=64, blank=True)
    sent_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("delivery")
        verbose_name_plural = _("deliveries")
        constraints = [
            models.UniqueConstraint(fields=["notification", "channel"], name="univ_notif_delivery_unique"),
        ]
        indexes = [models.Index(fields=["channel", "status", "created_at"], name="univ_notif_delivery_status")]

    def __str__(self) -> str:
        return f"{self.channel} {self.status} for {self.notification_id}"


class PushDevice(BaseModel):
    """A device registered for push. The token is never returned by the API."""

    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="push_devices")
    platform = models.CharField(max_length=16, choices=Platform.choices)
    token = models.TextField()
    #: Keyed hash of the token: dedupes devices without indexing the secret.
    token_hash = models.CharField(max_length=64, unique=True)
    name = models.CharField(max_length=100, blank=True)
    last_seen_at = models.DateTimeField(default=timezone.now)
    disabled_at = models.DateTimeField(null=True, blank=True)
    disabled_reason = models.CharField(max_length=32, blank=True)

    class Meta:
        verbose_name = _("push device")
        indexes = [models.Index(fields=["user", "disabled_at"], name="univ_notif_device_user")]

    def __str__(self) -> str:
        return f"{self.platform} device of {self.user_id}"
