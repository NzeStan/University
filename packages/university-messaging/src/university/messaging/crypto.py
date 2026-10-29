"""Encryption at rest for message text.

A database dump (or a curious query) shows ciphertext only. This is *not* end-to-end encryption:
the platform can decrypt, which is what lets participants read history on any device and lets
moderators review a message that a participant reports.
"""

from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

from university.core.conf import university_settings
from university.messaging.conf import messaging_settings


def _derived_key() -> bytes:
    secret = university_settings.get("SECURITY.HMAC_KEY") or settings.SECRET_KEY
    return base64.urlsafe_b64encode(hashlib.sha256(b"university-messaging:" + str(secret).encode()).digest())


def _fernet() -> MultiFernet:
    keys = messaging_settings.get("ENCRYPTION_KEYS") or [_derived_key()]
    return MultiFernet([Fernet(k if isinstance(k, bytes) else k.encode()) for k in keys])


def seal(text: str) -> str:
    return _fernet().encrypt(text.encode()).decode()


def unseal(cipher: str) -> str:
    if not cipher:
        return ""
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except (InvalidToken, ValueError):
        return ""
