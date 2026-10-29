"""Authorship cryptography for anonymous content.

Three primitives, each with a distinct purpose and key:

* :func:`owner_token` — ``HMAC(kind:object_id:user_id)``. Proves "this user
  wrote this item" when the user presents themselves, without storing the
  link. Tokens for the same user differ per item, so they cannot be used to
  group a user's items together.
* :func:`seal_identity` / :func:`open_identity` — Fernet (AES-128-CBC +
  HMAC-SHA256, from the audited ``cryptography`` library) encryption of the
  author's id, used only by authorised, audited reveals and sanctions.
  Encryption is randomised: equal ids produce unrelated ciphertexts.
* :func:`thread_token` / :func:`pseudonym_for` — a stable per-thread alias
  ("Quiet Heron") so conversations stay readable; aliases of one user differ
  across threads.

A database dump alone links no author to any item: tokens need the HMAC key
and ciphertexts need the identity key.
"""

from __future__ import annotations

import base64
import hashlib
from typing import Any

from cryptography.fernet import Fernet, InvalidToken, MultiFernet
from django.conf import settings

from university.anonymous.conf import anonymous_settings
from university.core.conf import university_settings
from university.core.crypto import constant_time_equals, keyed_hash


def _derived_key() -> bytes:
    secret = university_settings.get("SECURITY.HMAC_KEY") or settings.SECRET_KEY
    digest = hashlib.sha256(b"university-anonymous-identity:" + str(secret).encode()).digest()
    return base64.urlsafe_b64encode(digest)


def identity_keys_configured() -> bool:
    return bool(anonymous_settings.get("IDENTITY_KEYS"))


def _fernet() -> MultiFernet:
    keys = anonymous_settings.get("IDENTITY_KEYS") or [_derived_key()]
    return MultiFernet([Fernet(k if isinstance(k, bytes) else k.encode()) for k in keys])


def seal_identity(user_id: Any) -> str:
    return _fernet().encrypt(str(user_id).encode()).decode()


def open_identity(cipher: str) -> str | None:
    try:
        return _fernet().decrypt(cipher.encode()).decode()
    except (InvalidToken, ValueError):
        return None


def owner_token(kind: str, object_id: Any, user_id: Any) -> str:
    return keyed_hash(f"{kind}:{object_id}:{user_id}", purpose="anonymous-owner")


def owns(kind: str, object_id: Any, user: Any, token: str) -> bool:
    if user is None or not getattr(user, "is_authenticated", False):
        return False
    return constant_time_equals(owner_token(kind, object_id, user.pk), token)


def thread_token(post_id: Any, user_id: Any) -> str:
    return keyed_hash(f"{post_id}:{user_id}", purpose="anonymous-thread")


def pseudonym_for(token: str) -> str:
    adjectives = anonymous_settings.get("PSEUDONYM_ADJECTIVES")
    nouns = anonymous_settings.get("PSEUDONYM_NOUNS")
    value = int(token[:16], 16)
    return f"{adjectives[value % len(adjectives)]} {nouns[(value // len(adjectives)) % len(nouns)]}"


def sender_token(inbox_id: Any, user_id: Any) -> str:
    """Stable per (inbox, sender); unlinkable across inboxes without the key."""
    return keyed_hash(f"{inbox_id}:{user_id}", purpose="anonymous-inbox-sender")
