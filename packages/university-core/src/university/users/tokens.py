"""Signed, expiring tokens for email verification and email change.

Tokens embed a keyed hash of the address they were issued for, so they stop
working as soon as the address changes. Password-reset tokens use Django's
``default_token_generator`` (invalidated by any password or login change).
"""

from __future__ import annotations

from typing import Any

from django.core import signing

from university.core.conf import university_settings
from university.core.crypto import constant_time_equals, keyed_hash

EMAIL_VERIFICATION_SALT = "university.users.email_verification"
EMAIL_CHANGE_SALT = "university.users.email_change"


class InvalidToken(Exception):
    pass


def _email_digest(email: str) -> str:
    return keyed_hash(email.lower(), purpose="email-token")[:32]


def make_email_verification_token(user: Any) -> str:
    return signing.dumps({"u": str(user.pk), "e": _email_digest(user.email)}, salt=EMAIL_VERIFICATION_SALT)


def make_email_change_token(user: Any, new_email: str) -> str:
    return signing.dumps(
        {"u": str(user.pk), "e": _email_digest(new_email), "s": user.security_stamp[:8]},
        salt=EMAIL_CHANGE_SALT,
    )


def read_token(token: str, *, salt: str, max_age: int) -> dict[str, Any]:
    try:
        data = signing.loads(token, salt=salt, max_age=max_age)
    except signing.SignatureExpired as exc:
        raise InvalidToken("expired") from exc
    except signing.BadSignature as exc:
        raise InvalidToken("invalid") from exc
    if not isinstance(data, dict) or "u" not in data or "e" not in data:
        raise InvalidToken("invalid")
    return data


def read_email_verification_token(token: str) -> dict[str, Any]:
    ttl = int(university_settings.get("USERS.EMAIL_VERIFICATION_TTL_SECONDS"))
    return read_token(token, salt=EMAIL_VERIFICATION_SALT, max_age=ttl)


def read_email_change_token(token: str) -> dict[str, Any]:
    ttl = int(university_settings.get("USERS.EMAIL_CHANGE_TTL_SECONDS"))
    return read_token(token, salt=EMAIL_CHANGE_SALT, max_age=ttl)


def email_matches(digest: str, email: str) -> bool:
    return constant_time_equals(digest, _email_digest(email))
