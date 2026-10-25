"""Core hook implementations: data export and purge."""

from __future__ import annotations

from typing import Any

from university.notifications.models import Notification, NotificationActor, PushDevice


def export_data(user: Any) -> dict[str, Any]:
    notifications = Notification.objects.filter(recipient=user).order_by("-created_at")
    return {
        "notification_history": [
            {
                "verb": n.verb,
                "category": n.category,
                "target_type": n.target_type,
                "target_id": n.target_id,
                "created_at": n.created_at.isoformat(),
                "read_at": n.read_at.isoformat() if n.read_at else None,
            }
            for n in notifications.iterator()
        ],
        # Tokens are credentials for the device, so they are not exported.
        "push_devices": [
            {
                "platform": d.platform,
                "name": d.name,
                "created_at": d.created_at.isoformat(),
                "last_seen_at": d.last_seen_at.isoformat(),
                "active": d.disabled_at is None,
            }
            for d in PushDevice.objects.filter(user=user)
        ],
    }


def purge(user_id: Any) -> None:
    Notification.objects.filter(recipient_id=user_id).delete()
    # Others keep their notifications, but no longer attributed to this person.
    Notification.objects.filter(actor_id=user_id).update(actor=None)
    NotificationActor.objects.filter(user_id=user_id).delete()
    PushDevice.objects.filter(user_id=user_id).delete()
