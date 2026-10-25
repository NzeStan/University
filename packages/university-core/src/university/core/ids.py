"""Identifier generation.

Every externally visible University entity is keyed by a UUID. The UUID
version is configurable (``UNIVERSITY["IDS"]["UUID_VERSION"]``):

* ``4`` — random (default). Reveals nothing about the record.
* ``7`` — time-ordered (RFC 9562). Better index locality for very large
  tables, at the cost of embedding the creation time in the identifier.

Model fields reference :func:`new_uuid` so the choice can change without a
migration.
"""

from __future__ import annotations

import secrets
import time
import uuid


def uuid7() -> uuid.UUID:
    """Return an RFC 9562 version 7 UUID (uses the stdlib when available)."""
    native = getattr(uuid, "uuid7", None)
    if native is not None:
        return native()
    unix_ms = time.time_ns() // 1_000_000
    rand_a = secrets.randbits(12)
    rand_b = secrets.randbits(62)
    value = (unix_ms & ((1 << 48) - 1)) << 80
    value |= 0x7 << 76
    value |= rand_a << 64
    value |= 0b10 << 62
    value |= rand_b
    return uuid.UUID(int=value)


def new_uuid() -> uuid.UUID:
    """Default primary-key factory for University models."""
    from university.core.conf import university_settings

    if university_settings.get("IDS.UUID_VERSION", 4) == 7:
        return uuid7()
    return uuid.uuid4()


def is_valid_uuid(value: object) -> bool:
    """Return True if ``value`` parses as a UUID."""
    if isinstance(value, uuid.UUID):
        return True
    try:
        uuid.UUID(str(value))
    except (TypeError, ValueError, AttributeError):
        return False
    return True
