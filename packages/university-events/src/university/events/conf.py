"""Settings for the events module (``UNIVERSITY["EVENTS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    "CATEGORIES": [
        "academic",
        "career",
        "social",
        "sports",
        "arts",
        "religious",
        "tech",
        "workshop",
        "conference",
        "community",
        "other",
    ],
    # "verified_users": anyone with a verified email may host personal events;
    # "permission": only holders of events.create. Hosting for a scope always
    # requires events.manage at that scope.
    "CREATION_POLICY": "verified_users",
    "MAX_UPCOMING_EVENTS_PER_USER": 20,
    "MAX_DURATION_DAYS": 30,
    "MAX_TICKET_TYPES": 10,
    "MAX_SESSIONS": 100,
    "MAX_ORGANIZERS": 20,
    # Paid tickets need university-payments (or any module that pays Core payables):
    # tickets are sold as the "events.registration" payable.
    "PAID_TICKETS_ENABLED": False,
    "DEFAULT_CURRENCY": "NGN",
    "CURRENCIES": ["NGN", "GHS", "KES", "ZAR", "XOF", "EGP", "USD"],
    "PAYMENT_HOLD_MINUTES": 15,
    # Paid tickets cancelled by the attendee are refunded until this many hours before the start.
    # Declines by organizers and cancelled events are always refunded.
    "REFUND_ON_ATTENDEE_CANCEL": True,
    "REFUND_CUTOFF_HOURS": 24,
    # Promote the first waitlisted person when a seat frees up.
    "WAITLIST_AUTO_PROMOTE": True,
    # Reminders go out this many hours before the start (send_event_reminders).
    "REMINDER_HOURS": 24,
    # Public event page, used in calendar files ({id} and {slug} are substituted).
    "EVENT_URL": "http://localhost:3000/events/{slug}",
    "COVER_MIME_TYPES": ["image/jpeg", "image/png", "image/webp"],
    "COVER_MAX_BYTES": 5 * 1024 * 1024,
    # Registrations of events that ended this many days ago are deleted.
    "REGISTRATION_RETENTION_DAYS": 730,
}

events_settings = ModuleSettings("EVENTS", DEFAULTS)
