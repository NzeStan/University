"""Settings for subscriptions (``UNIVERSITY["SUBSCRIPTIONS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Plan key -> definition. Prices are per interval, per currency, in minor units. A plan's
    # entitlements are keys other modules check with university.core.entitlements.
    "PLANS": {
        "plus": {
            "name": "Plus",
            "description": "No adverts, a profile badge and more control over your inbox.",
            "prices": {"month": {"NGN": 150000, "USD": 299}, "year": {"NGN": 1500000, "USD": 2999}},
            "entitlements": ["premium.ad_free", "premium.badge", "premium.inbox_filters"],
        },
        "creator_pro": {
            "name": "Creator Pro",
            "description": "Everything in Plus, with deeper analytics and priority sponsorship placement.",
            "prices": {"month": {"NGN": 500000, "USD": 999}, "year": {"NGN": 5000000, "USD": 9999}},
            "entitlements": [
                "premium.ad_free",
                "premium.badge",
                "premium.inbox_filters",
                "creator.analytics_pro",
                "creator.priority_listing",
            ],
        },
    },
    # Human labels for entitlement keys, shown on the plans page.
    "ENTITLEMENT_LABELS": {
        "premium.ad_free": "No adverts",
        "premium.badge": "Premium badge on your profile",
        "premium.inbox_filters": "Anonymous inbox filters",
        "creator.analytics_pro": "Advanced creator analytics",
        "creator.priority_listing": "Priority in the creator directory",
    },
    "INTERVAL_DAYS": {"month": 30, "year": 365},
    # A renewal can be paid this many days before the period ends.
    "RENEWAL_WINDOW_DAYS": 7,
    # Reminder sent this many days before the period ends.
    "REMINDER_DAYS": 3,
    # After a period ends unpaid, entitlements continue this long before the subscription expires.
    "GRACE_DAYS": 3,
}

subscriptions_settings = ModuleSettings("SUBSCRIPTIONS", DEFAULTS)


def plans() -> dict[str, dict[str, Any]]:
    return dict(subscriptions_settings.get("PLANS") or {})


def price(plan: str, interval: str, currency: str) -> int | None:
    value = (plans().get(plan, {}).get("prices", {}).get(interval) or {}).get(currency)
    return int(value) if value else None
