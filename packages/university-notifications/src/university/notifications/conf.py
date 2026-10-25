"""Settings for the notifications module (``UNIVERSITY["NOTIFICATIONS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Each category sets per-channel defaults. ``email`` is False, "immediate"
    # or "digest" (collected into the recipient's daily/weekly digest).
    # ``mandatory`` categories always appear in-app; ``bypass_quiet_hours``
    # categories may push during quiet hours. People override channels per
    # category in their notification settings (``me/notifications/``).
    "CATEGORIES": {
        "security": {
            "label": "Security alerts",
            "in_app": True,
            "email": False,  # Core already emails security alerts.
            "push": True,
            "sms": False,
            "mandatory": True,
            "bypass_quiet_hours": True,
        },
        "moderation": {
            "label": "Moderation decisions",
            "in_app": True,
            "email": "immediate",
            "push": True,
            "sms": False,
            "mandatory": True,
        },
        "account": {"label": "Account and institution", "in_app": True, "email": "immediate", "push": True},
        "communities": {"label": "Communities", "in_app": True, "email": "immediate", "push": True},
        "events": {"label": "Events and tickets", "in_app": True, "email": "immediate", "push": True},
        "creator": {"label": "Creator and sponsorships", "in_app": True, "email": "immediate", "push": True},
        "commerce": {"label": "Orders and payments", "in_app": True, "email": "immediate", "push": True},
        "podcasts": {"label": "Podcasts", "in_app": True, "email": "digest", "push": True},
        "media": {"label": "Uploads", "in_app": True, "email": False, "push": False},
        "mentions": {"label": "Mentions", "in_app": True, "email": "digest", "push": True},
        "comments": {"label": "Comments and replies", "in_app": True, "email": "digest", "push": True},
        "follows": {"label": "Followers", "in_app": True, "email": "digest", "push": True},
        "reactions": {"label": "Reactions", "in_app": True, "email": "digest", "push": False},
        "reposts": {"label": "Reposts", "in_app": True, "email": "digest", "push": True},
    },
    # Verb keys to switch off entirely, e.g. ["social.reaction"].
    "DISABLED_VERBS": [],
    # Delivery channels (dotted paths). Set one to None to disable it platform-wide.
    "CHANNELS": {
        "email": "university.notifications.channels.EmailChannel",
        "push": "university.notifications.channels.PushChannel",
        "sms": "university.notifications.channels.SMSChannel",
    },
    # Push provider: NullPushProvider, FCMPushProvider or ExpoPushProvider.
    "PUSH_PROVIDER": "university.notifications.push.NullPushProvider",
    "PUSH_PROVIDER_OPTIONS": {},
    # False sends a generic "You have a new notification" to lock screens.
    "PUSH_PREVIEWS": True,
    "PUSH_MAX_PER_HOUR": 30,
    "MAX_DEVICES_PER_USER": 10,
    "MAX_DELIVERY_ATTEMPTS": 5,
    # Retries back off exponentially from this delay.
    "RETRY_BASE_SECONDS": 60,
    "DIGEST_MAX_ITEMS": 20,
    # Links used in emails and push payloads. {id} is the notification id.
    "OPEN_URL": "http://localhost:3000/notifications/{id}",
    "LIST_URL": "http://localhost:3000/notifications",
    "PREFERENCES_URL": "http://localhost:3000/settings/notifications",
    "SITE_NAME": "University",
    # Handle events on the task backend instead of in the publishing process.
    "ASYNC_HANDLERS": False,
    # Retention (days; None keeps forever).
    "READ_RETENTION_DAYS": 90,
    "UNREAD_RETENTION_DAYS": 365,
    "DELIVERY_RETENTION_DAYS": 30,
    "DISABLED_DEVICE_RETENTION_DAYS": 30,
    # Devices not seen for this long stop receiving pushes.
    "DEVICE_STALE_DAYS": 270,
}

notification_settings = ModuleSettings("NOTIFICATIONS", DEFAULTS)
