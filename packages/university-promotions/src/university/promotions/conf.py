"""Settings for promotions (``UNIVERSITY["PROMOTIONS"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Price per 1,000 delivered impressions, per currency (minor units). Budgets buy impressions.
    "CPM_MINOR": {"NGN": 150000, "GHS": 1500, "KES": 15000, "USD": 300},
    "MIN_BUDGET_MINOR": {"NGN": 500000, "GHS": 5000, "KES": 50000, "USD": 1000},
    "PLACEMENTS": ["feed", "events", "marketplace", "opportunities"],
    # Content people can boost (their own items only): content type -> label.
    "BOOSTABLE": {
        "social.post": "Post",
        "events.event": "Event",
        "marketplace.listing": "Listing",
        "opportunities.opportunity": "Opportunity",
        "podcast.show": "Podcast",
    },
    # Campaigns must be paid for (via university-payments) before review. False: free (testing).
    "REQUIRE_PAYMENT": True,
    # Each viewer sees a campaign at most this many times a day (frequency cap, no tracking kept).
    "DAILY_FREQUENCY_CAP": 3,
    "MAX_ITEMS_PER_REQUEST": 3,
    # Viewers holding this entitlement (e.g. a premium plan) aren't shown adverts. None: everyone is.
    "AD_FREE_ENTITLEMENT": "premium.ad_free",
    "IMAGE_MIME_TYPES": ["image/jpeg", "image/png", "image/webp"],
    "IMAGE_MAX_BYTES": 3 * 1024 * 1024,
    # Impression/click tokens stay valid this long after an item is served.
    "TOKEN_MAX_AGE_SECONDS": 6 * 60 * 60,
}

promotions_settings = ModuleSettings("PROMOTIONS", DEFAULTS)
