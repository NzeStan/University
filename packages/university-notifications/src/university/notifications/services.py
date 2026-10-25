"""Notification services: create, aggregate, read state and devices.

:func:`notify` is the single entry point for creating notifications, used by
the event handlers and available to project code::

    from university.notifications.services import notify

    notify(recipient=user, verb="community.invited", actor=inviter,
           target_type="community.community", target_id=community.pk)

It enforces, in order: the verb is enabled; the recipient is active; for
actor verbs, the actor is active, isn't the recipient and passes Core's
``users.can_interact(actor, recipient, "notify")`` hook (so blocks apply);
and the recipient's preferences leave at least one channel open.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models.functions import Coalesce
from django.dispatch import Signal
from django.utils import timezone

from university.core.crypto import keyed_hash
from university.core.events import publish
from university.core.exceptions import NotFound, ValidationError
from university.core.hooks import Hook, hooks
from university.core.ids import is_valid_uuid
from university.core.ratelimit import rate_limit
from university.notifications import events
from university.notifications.channels import enabled_channels
from university.notifications.conf import notification_settings
from university.notifications.constants import Channel
from university.notifications.delivery import plan_deliveries
from university.notifications.models import Notification, NotificationActor, PushDevice
from university.notifications.preferences import channel_mode, get_category
from university.notifications.verbs import Verb, get_verb

#: Sent with ``notification=<Notification>, created=<bool>`` for real-time gateways.
notification_created = Signal()

TOKEN_PURPOSE = "notifications.push_token"  # noqa: S105 - a hash purpose label, not a secret


def _user(value: Any) -> Any:
    if value is None:
        return None
    if hasattr(value, "is_active") and hasattr(value, "pk"):
        return value
    if not is_valid_uuid(value):
        return None
    return get_user_model().objects.filter(pk=value).first()


def reachable(user: Any, category: Any) -> bool:
    """Active people get everything; suspended or banned people still get mandatory notices."""
    if user is None or getattr(user, "is_deleted", False):
        return False
    return bool(user.is_active or category.mandatory)


def _clean_data(data: dict[str, Any] | None) -> dict[str, Any]:
    """Identifiers and enum values only: short scalars, few keys."""
    clean: dict[str, Any] = {}
    for key, value in list((data or {}).items())[:10]:
        if value is None or isinstance(value, bool | int):
            clean[str(key)[:32]] = value
        else:
            clean[str(key)[:32]] = str(value)[:64]
    return clean


def _announce(notification: Notification, *, created: bool) -> None:
    if not notification.in_app:
        return
    notification_created.send(sender=Notification, notification=notification, created=created)
    publish(
        events.NOTIFICATION_CREATED,
        {"notification_id": notification.pk, "recipient_id": notification.recipient_id, "aggregated": not created},
    )


def notify(
    *,
    recipient: Any,
    verb: str,
    actor: Any = None,
    target_type: str = "",
    target_id: Any = "",
    data: dict[str, Any] | None = None,
    group_key: str = "",
) -> Notification | None:
    """Create (or aggregate into) a notification. Returns ``None`` when nothing was created."""
    spec = get_verb(verb)
    if verb in (notification_settings.get("DISABLED_VERBS") or []):
        return None
    category = get_category(spec.category)
    recipient = _user(recipient)
    if not reachable(recipient, category):
        return None
    if spec.show_actor:
        actor = _user(actor)
        if actor is None or not actor.is_active or actor.pk == recipient.pk:
            return None
        if not hooks.allows(Hook.USER_CAN_INTERACT, actor, recipient, "notify"):
            return None
    else:
        actor = None  # System notices never reveal who acted (e.g. which moderator).
    from university.users.services.preferences import get_notification_settings

    prefs = get_notification_settings(recipient)
    in_app = bool(channel_mode(prefs, category, Channel.IN_APP))
    if not in_app and not any(channel_mode(prefs, category, ch) for ch in enabled_channels()):
        return None
    fields = {
        "target_type": target_type[:64],
        "target_id": str(target_id or "")[:64],
        "data": _clean_data(data),
    }
    group_key = group_key[:160]
    with transaction.atomic():
        if group_key:
            existing = _unread_group(recipient, group_key)
            if existing is not None:
                return _aggregate(existing, spec, actor, fields)
        try:
            with transaction.atomic():
                notification = Notification.objects.create(
                    recipient=recipient,
                    verb=verb,
                    category=spec.category,
                    actor=actor,
                    group_key=group_key,
                    in_app=in_app,
                    **fields,
                )
        except IntegrityError:  # A concurrent event created the group first.
            existing = _unread_group(recipient, group_key)
            return _aggregate(existing, spec, actor, fields) if existing else None
        if actor is not None:
            NotificationActor.objects.create(notification=notification, user=actor)
        plan_deliveries(notification, prefs, category)
    _announce(notification, created=True)
    return notification


def _unread_group(recipient: Any, group_key: str) -> Notification | None:
    return (
        Notification.objects.select_for_update()
        .filter(recipient=recipient, group_key=group_key, read_at__isnull=True)
        .first()
    )


def _aggregate(existing: Notification, spec: Verb, actor: Any, fields: dict[str, Any]) -> Notification | None:
    # Non-aggregating verbs dedupe: the same unread event isn't repeated.
    if not spec.aggregates or actor is None:
        return None
    try:
        with transaction.atomic():
            NotificationActor.objects.create(notification=existing, user=actor)
    except IntegrityError:
        return None  # This actor is already counted (e.g. reacted, unreacted, reacted).
    existing.actor = actor
    existing.actor_count += 1
    existing.last_activity_at = timezone.now()
    existing.seen_at = None
    existing.target_type, existing.target_id, existing.data = fields["target_type"], fields["target_id"], fields["data"]
    existing.save(
        update_fields=[
            "actor",
            "actor_count",
            "last_activity_at",
            "seen_at",
            "target_type",
            "target_id",
            "data",
            "updated_at",
        ]
    )
    _announce(existing, created=False)
    return existing


# ------------------------------------------------------------ read state
def _own(user: Any, notification_id: Any) -> Notification:
    notification = Notification.objects.filter(pk=notification_id, recipient=user, in_app=True).first()
    if notification is None:
        raise NotFound("Notification not found.")
    return notification


def get_notification(*, user: Any, notification_id: Any) -> Notification:
    return _own(user, notification_id)


def mark_read(*, user: Any, notification_id: Any) -> Notification:
    notification = _own(user, notification_id)
    if notification.read_at is None:
        now = timezone.now()
        notification.read_at = now
        notification.seen_at = notification.seen_at or now
        notification.save(update_fields=["read_at", "seen_at", "updated_at"])
    return notification


def mark_unread(*, user: Any, notification_id: Any) -> Notification:
    notification = _own(user, notification_id)
    if notification.read_at is not None:
        notification.read_at = None
        # Detach from its group so it can't collide with a newer unread row.
        notification.group_key = ""
        notification.save(update_fields=["read_at", "group_key", "updated_at"])
    return notification


def mark_all_read(*, user: Any, category: str | None = None, before: Any = None) -> int:
    qs = Notification.objects.filter(recipient=user, in_app=True, read_at__isnull=True)
    if category:
        qs = qs.filter(category=category)
    if before is not None:  # Only what the client has actually displayed.
        qs = qs.filter(last_activity_at__lte=before)
    now = timezone.now()
    return qs.update(read_at=now, seen_at=Coalesce("seen_at", now), updated_at=now)


def mark_all_seen(*, user: Any) -> int:
    now = timezone.now()
    return Notification.objects.filter(recipient=user, in_app=True, seen_at__isnull=True).update(
        seen_at=now, updated_at=now
    )


def delete_notification(*, user: Any, notification_id: Any) -> None:
    _own(user, notification_id).delete()


def remove_between(user_a: Any, user_b: Any) -> int:
    """Delete notifications either person caused the other (used when one blocks the other)."""
    from django.db.models import Q

    deleted, _ = Notification.objects.filter(
        Q(recipient_id=user_a, actor_id=user_b) | Q(recipient_id=user_b, actor_id=user_a)
    ).delete()
    return deleted


# --------------------------------------------------------------- devices
def _token_hash(token: str) -> str:
    return keyed_hash(token, purpose=TOKEN_PURPOSE)


@transaction.atomic
def register_device(*, user: Any, platform: str, token: str, name: str = "") -> PushDevice:
    rate_limit("notifications_device_register", key=str(user.pk))
    token = (token or "").strip()
    if not 16 <= len(token) <= 4096:
        raise ValidationError(details={"token": ["Enter a valid push token."]})
    now = timezone.now()
    token_hash = _token_hash(token)
    device = PushDevice.objects.select_for_update().filter(token_hash=token_hash).first()
    if device is not None:
        # The same physical device signed in to another account: it moves.
        device.user = user
        device.platform = platform
        device.name = name[:100]
        device.token = token
        device.last_seen_at = now
        device.disabled_at = None
        device.disabled_reason = ""
        device.save()
        return device
    limit = int(notification_settings.get("MAX_DEVICES_PER_USER", 10))
    active = PushDevice.objects.filter(user=user, disabled_at__isnull=True).order_by("last_seen_at")
    surplus = active.count() - limit + 1
    if surplus > 0:
        stale = list(active.values_list("pk", flat=True)[:surplus])
        PushDevice.objects.filter(pk__in=stale).update(disabled_at=now, disabled_reason="replaced")
    try:
        with transaction.atomic():
            return PushDevice.objects.create(
                user=user, platform=platform, token=token, token_hash=token_hash, name=name[:100], last_seen_at=now
            )
    except IntegrityError:  # Registered concurrently.
        return PushDevice.objects.get(token_hash=token_hash)


def unregister_device(*, user: Any, device_id: Any = None, token: str | None = None) -> None:
    qs = PushDevice.objects.filter(user=user)
    if device_id is not None:
        qs = qs.filter(pk=device_id)
    elif token:
        qs = qs.filter(token_hash=_token_hash(token.strip()))
    else:
        raise ValidationError("Identify the device.", code="device_required")
    if not qs.delete()[0] and device_id is not None:
        raise NotFound("Device not found.")


def disable_devices(user_id: Any, reason: str) -> int:
    return PushDevice.objects.filter(user_id=user_id, disabled_at__isnull=True).update(
        disabled_at=timezone.now(), disabled_reason=reason[:32]
    )
