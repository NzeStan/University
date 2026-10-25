"""Delivery: plan external channels, send with retries, and email digests.

Each external channel gets one :class:`~university.notifications.models.Delivery`
row. Immediate deliveries run as tasks (after commit) and are *claimed*
atomically, so at-least-once task queues never send twice. Failures back off
exponentially up to ``MAX_DELIVERY_ATTEMPTS``.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from django.utils import timezone

from university.core.tasks import schedule, task
from university.notifications.channels import DIGEST_TEMPLATE, enabled_channels, get_channel, send_email
from university.notifications.conf import notification_settings
from university.notifications.constants import (
    EMAIL_DIGEST,
    EXTERNAL_CHANNELS,
    INTERRUPTING_CHANNELS,
    Channel,
    DeliveryStatus,
)
from university.notifications.models import Delivery, Notification
from university.notifications.preferences import Category, channel_mode, get_category, in_quiet_hours
from university.notifications.rendering import render

logger = logging.getLogger("university.notifications")


def plan_deliveries(notification: Notification, prefs: Any, category: Category) -> list[Delivery]:
    enabled = set(enabled_channels())
    rows = []
    for channel in EXTERNAL_CHANNELS:
        if channel not in enabled:
            continue
        mode = channel_mode(prefs, category, channel)
        if not mode:
            continue
        status = DeliveryStatus.PENDING
        if channel == Channel.EMAIL and mode == EMAIL_DIGEST:
            if prefs.digest_frequency == "never":
                continue
            status = DeliveryStatus.DIGEST
        rows.append(Delivery(notification=notification, channel=channel, status=status))
    created = Delivery.objects.bulk_create(rows)
    for delivery in created:
        if delivery.status == DeliveryStatus.PENDING:
            schedule(deliver, (str(delivery.pk),))
    return created


def _finish(delivery: Delivery, status: str, reason: str = "") -> None:
    delivery.status = status
    delivery.reason = reason[:64]
    fields = ["status", "reason", "attempts", "updated_at"]
    if status == DeliveryStatus.SENT:
        delivery.sent_at = timezone.now()
        fields.append("sent_at")
    delivery.save(update_fields=fields)


def _over_hourly_cap(delivery: Delivery) -> bool:
    cap = notification_settings.get("PUSH_MAX_PER_HOUR")
    if not cap:
        return False
    since = timezone.now() - dt.timedelta(hours=1)
    sent = Delivery.objects.filter(
        channel=Channel.PUSH,
        status=DeliveryStatus.SENT,
        sent_at__gte=since,
        notification__recipient_id=delivery.notification.recipient_id,
    ).count()
    return sent >= int(cap)


@task(name="university.notifications.deliver")
def deliver(delivery_id: str) -> None:
    # Claim: only one worker moves a delivery from pending to sending.
    if not Delivery.objects.filter(pk=delivery_id, status=DeliveryStatus.PENDING).update(
        status=DeliveryStatus.SENDING, updated_at=timezone.now()
    ):
        return
    delivery = Delivery.objects.select_related("notification__recipient", "notification__actor").get(pk=delivery_id)
    notification = delivery.notification
    user = notification.recipient
    category = get_category(notification.category)
    from university.notifications.services import reachable

    if not reachable(user, category):
        return _finish(delivery, DeliveryStatus.SKIPPED, "recipient_inactive")
    if notification.read_at is not None:
        return _finish(delivery, DeliveryStatus.SKIPPED, "already_read")
    channel = get_channel(delivery.channel)
    if channel is None:
        return _finish(delivery, DeliveryStatus.SKIPPED, "channel_disabled")
    if not channel.is_available(user):
        return _finish(delivery, DeliveryStatus.SKIPPED, "unreachable")
    if delivery.channel in INTERRUPTING_CHANNELS and not category.bypass_quiet_hours:
        from university.users.services.preferences import get_notification_settings

        if in_quiet_hours(user, get_notification_settings(user)):
            return _finish(delivery, DeliveryStatus.SUPPRESSED, "quiet_hours")
        if delivery.channel == Channel.PUSH and _over_hourly_cap(delivery):
            return _finish(delivery, DeliveryStatus.SUPPRESSED, "hourly_cap")
    delivery.attempts += 1
    try:
        channel.send(user, notification, render(notification, user))
    except Exception as exc:
        code = str(getattr(exc, "code", "") or type(exc).__name__)
        logger.warning("Notification delivery %s via %s failed (%s)", delivery.pk, delivery.channel, code)
        if delivery.attempts >= int(notification_settings.get("MAX_DELIVERY_ATTEMPTS", 5)):
            return _finish(delivery, DeliveryStatus.FAILED, code)
        _finish(delivery, DeliveryStatus.PENDING, code)
        delay = int(notification_settings.get("RETRY_BASE_SECONDS", 60)) * 2 ** (delivery.attempts - 1)
        schedule(deliver, (str(delivery.pk),), on_commit=False, countdown=delay)
        return None
    return _finish(delivery, DeliveryStatus.SENT)


@task(name="university.notifications.send_digests")
def send_digests(frequency: str) -> int:
    """Email each person whose digest frequency is ``frequency`` their queued notifications."""
    from university.users.models import NotificationSettings

    users = NotificationSettings.objects.filter(digest_frequency=frequency, email_enabled=True).values("user_id")
    recipients = (
        Delivery.objects.filter(channel=Channel.EMAIL, status=DeliveryStatus.DIGEST)
        .filter(notification__recipient_id__in=users)
        .values_list("notification__recipient_id", flat=True)
        .distinct()
    )
    sent = 0
    for recipient_id in list(recipients):
        try:
            sent += _send_digest(recipient_id)
        except Exception:
            logger.exception("Digest for %s failed", recipient_id)
    return sent


def _send_digest(recipient_id: Any) -> int:
    queued = Delivery.objects.filter(
        channel=Channel.EMAIL, status=DeliveryStatus.DIGEST, notification__recipient_id=recipient_id
    )
    now = timezone.now()
    queued.filter(notification__read_at__isnull=False).update(
        status=DeliveryStatus.SKIPPED, reason="already_read", updated_at=now
    )
    rows = list(queued.select_related("notification__recipient", "notification__actor").order_by("-created_at"))
    if not rows:
        return 0
    user = rows[0].notification.recipient
    channel = get_channel(Channel.EMAIL)
    ids = [d.pk for d in rows]
    if channel is None or not user.is_active or not channel.is_available(user):  # Digests: active people only.
        Delivery.objects.filter(pk__in=ids).update(status=DeliveryStatus.SKIPPED, reason="unreachable", updated_at=now)
        return 0
    limit = int(notification_settings.get("DIGEST_MAX_ITEMS", 20))
    items = []
    for delivery in rows[:limit]:
        rendered = render(delivery.notification, user)
        items.append({"title": rendered.title, "url": rendered.url})
    context = {"items": items, "total": len(rows), "more": max(len(rows) - limit, 0)}
    send_email(user, DIGEST_TEMPLATE, context, "digest")
    Delivery.objects.filter(pk__in=ids).update(status=DeliveryStatus.SENT, sent_at=now, attempts=1, updated_at=now)
    return 1
