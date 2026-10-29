"""Settings for the opportunities module (``UNIVERSITY["OPPORTUNITIES"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    # Posting needs a verified email address (and passes the spam filter).
    "REQUIRE_VERIFIED_EMAIL": True,
    "MAX_OPEN_PER_USER": 20,
    "DESCRIPTION_MAX_LENGTH": 8000,
    "CURRENCIES": ["NGN", "GHS", "KES", "ZAR", "XOF", "EGP", "USD"],
    "DEFAULT_CURRENCY": "NGN",
    # CVs (in-app applications): private storage, validated by content.
    "RESUME_MIME_TYPES": ["application/pdf"],
    "RESUME_MAX_BYTES": 5 * 1024 * 1024,
    # Applications (and their CVs) are deleted this long after the opportunity closes.
    "APPLICATION_RETENTION_DAYS": 180,
    # Open opportunities past their deadline close automatically (close_expired task).
    "AUTO_CLOSE_AFTER_DEADLINE": True,
}

opportunities_settings = ModuleSettings("OPPORTUNITIES", DEFAULTS)
