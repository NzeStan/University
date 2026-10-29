"""Settings for the messaging module (``UNIVERSITY["MESSAGING"]``)."""

from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    "MESSAGE_MAX_LENGTH": 4000,
    "MAX_GROUP_SIZE": 50,
    # Senders can edit a message for this long after sending it.
    "EDIT_WINDOW_MINUTES": 15,
    # Fernet keys (urlsafe base64, 32 bytes) encrypting message text at rest. The first key
    # encrypts; all keys decrypt (rotation). Empty: a key is derived from SECURITY.HMAC_KEY.
    "ENCRYPTION_KEYS": [],
    "REQUIRE_VERIFIED_EMAIL": True,
    # Deleted messages keep a tombstone ("This message was deleted") for this many days, then go.
    "DELETED_RETENTION_DAYS": 30,
}

messaging_settings = ModuleSettings("MESSAGING", DEFAULTS)
