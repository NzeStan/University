"""Cryptographic helpers.

University never invents cryptography: passwords use Django's hashers and
everything here wraps the standard library (``hmac``, ``hashlib``,
``secrets``).

Keyed hashes (:func:`keyed_hash`) are used to store high-entropy secrets
(refresh tokens, API keys, OTP codes) and to index identifiers without
storing them in plaintext. A database leak alone is not enough to verify a
guess — the attacker also needs the HMAC key. Keys can be rotated through
``SECURITY.HMAC_KEY_FALLBACKS``.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import string

from django.conf import settings

from university.core.conf import university_settings


def _key_material() -> list[bytes]:
    primary = university_settings.get("SECURITY.HMAC_KEY") or settings.SECRET_KEY
    fallbacks = list(university_settings.get("SECURITY.HMAC_KEY_FALLBACKS") or [])
    if not university_settings.get("SECURITY.HMAC_KEY"):
        fallbacks.extend(getattr(settings, "SECRET_KEY_FALLBACKS", []) or [])
    return [str(k).encode() for k in [primary, *fallbacks] if k]


def _derive(key: bytes, purpose: str) -> bytes:
    return hashlib.sha256(b"university:" + purpose.encode() + b":" + key).digest()


def _to_bytes(value: str | bytes) -> bytes:
    return value if isinstance(value, bytes) else value.encode()


def keyed_hash(value: str | bytes, *, purpose: str) -> str:
    """HMAC-SHA256 of ``value`` under a key derived for ``purpose`` (hex)."""
    key = _derive(_key_material()[0], purpose)
    return hmac.new(key, _to_bytes(value), hashlib.sha256).hexdigest()


def keyed_hash_candidates(value: str | bytes, *, purpose: str) -> list[str]:
    """Hashes of ``value`` under the current and every fallback key.

    Use for lookups by hash during key rotation: ``filter(hash__in=...)``.
    """
    data = _to_bytes(value)
    return [hmac.new(_derive(key, purpose), data, hashlib.sha256).hexdigest() for key in _key_material()]


def verify_keyed_hash(value: str | bytes, expected: str, *, purpose: str) -> bool:
    """Constant-time check of ``value`` against a stored keyed hash."""
    matched = False
    for candidate in keyed_hash_candidates(value, purpose=purpose):
        # Evaluate all candidates to keep timing independent of key position.
        matched |= hmac.compare_digest(candidate, expected)
    return matched


def sha256_hex(value: str | bytes) -> str:
    return hashlib.sha256(_to_bytes(value)).hexdigest()


def constant_time_equals(a: str | bytes, b: str | bytes) -> bool:
    return hmac.compare_digest(_to_bytes(a), _to_bytes(b))


def generate_token(nbytes: int = 32) -> str:
    """URL-safe random token with ``nbytes`` of entropy."""
    return secrets.token_urlsafe(nbytes)


def generate_numeric_code(length: int = 6) -> str:
    """Uniformly random numeric code (for OTPs)."""
    return "".join(secrets.choice(string.digits) for _ in range(length))


def mask_email(email: str) -> str:
    """``ada.lovelace@example.com`` -> ``a***e@example.com``."""
    local, sep, domain = email.partition("@")
    if not sep:
        return "***"
    if len(local) <= 2:
        masked = local[:1] + "***"
    else:
        masked = f"{local[0]}***{local[-1]}"
    return f"{masked}@{domain}"


def mask_phone(phone: str) -> str:
    """``+2348012345678`` -> ``+234******5678``."""
    if len(phone) <= 4:
        return "****"
    visible_prefix = 4 if phone.startswith("+") else 0
    return phone[:visible_prefix] + "*" * (len(phone) - visible_prefix - 4) + phone[-4:]
