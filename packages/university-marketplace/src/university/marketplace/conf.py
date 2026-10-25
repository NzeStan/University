"""Settings for the marketplace module (``UNIVERSITY["MARKETPLACE"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Seeded on migrate as {key: name} or {key: {"name": ..., "children": {...}}}.
    "CATEGORIES": {
        "electronics": {
            "name": "Electronics",
            "children": {"phones": "Phones", "laptops": "Laptops", "accessories": "Accessories"},
        },
        "books": {"name": "Books", "children": {"textbooks": "Textbooks", "novels": "Novels"}},
        "fashion": "Fashion",
        "hostel": {"name": "Hostel and home", "children": {"furniture": "Furniture", "kitchen": "Kitchen"}},
        "services": {
            "name": "Services",
            "children": {"tutoring": "Tutoring", "design": "Design", "repairs": "Repairs"},
        },
        "food": "Food",
        "other": "Other",
    },
    "CURRENCIES": ["NGN", "GHS", "KES", "ZAR", "XOF", "EGP", "USD"],
    "DEFAULT_CURRENCY": "NGN",
    # Platform commission on online orders, in basis points (100 = 1%).
    "PLATFORM_FEE_BPS": 0,
    "REQUIRE_VERIFIED_EMAIL": True,
    "MAX_ACTIVE_LISTINGS": 50,
    "MAX_QUANTITY_PER_ORDER": 20,
    "MAX_IMAGES": 8,
    "IMAGE_MIME_TYPES": ["image/jpeg", "image/png", "image/webp"],
    "IMAGE_MAX_BYTES": 5 * 1024 * 1024,
    # Cash on pickup: common on campuses, but without buyer protection.
    "ALLOW_CASH_ON_PICKUP": True,
    # Unpaid online orders release their stock after this long.
    "PAYMENT_WINDOW_MINUTES": 30,
    # Fulfilled online orders complete automatically (releasing escrow) after this many days
    # unless the buyer opens a dispute.
    "AUTO_COMPLETE_DAYS": 7,
    # Delivery addresses and phone numbers are erased this long after an order closes.
    "DELIVERY_DETAILS_RETENTION_DAYS": 30,
}

marketplace_settings = ModuleSettings("MARKETPLACE", DEFAULTS)
