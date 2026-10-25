"""Access-token issuance.

The access token format is pluggable via ``AUTH.TOKEN_ISSUER``. The default
:class:`JWTTokenIssuer` uses PyJWT with a single pinned algorithm (no
``alg`` confusion, no ``none``), and binds each token to a session and to a
fingerprint of the user's security stamp, so revocation and credential
changes take effect immediately despite tokens being stateless.

Refresh tokens are *not* JWTs: they are opaque random strings stored hashed
and rotated on every use (see :mod:`university.security.services.sessions`).
"""

from __future__ import annotations

import datetime as dt
import uuid
from dataclasses import dataclass
from typing import Any, Protocol

import jwt
from django.conf import settings
from django.utils import timezone
from rest_framework import exceptions

from university.core.conf import university_settings
from university.core.crypto import keyed_hash


def stamp_fingerprint(stamp: str) -> str:
    return keyed_hash(stamp, purpose="token-stamp")[:16]


@dataclass(frozen=True)
class AccessClaims:
    user_id: str
    session_id: str
    stamp: str
    token_id: str
    issued_at: dt.datetime
    expires_at: dt.datetime


@dataclass(frozen=True)
class TokenPair:
    access: str
    refresh: str
    access_expires_at: dt.datetime
    refresh_expires_at: dt.datetime
    session_id: Any

    def as_dict(self) -> dict[str, Any]:
        return {
            "token_type": "Bearer",
            "access": self.access,
            "refresh": self.refresh,
            "access_expires_at": self.access_expires_at.isoformat(),
            "refresh_expires_at": self.refresh_expires_at.isoformat(),
            "session_id": str(self.session_id),
        }


class TokenIssuer(Protocol):
    def issue_access(self, *, user: Any, session: Any) -> tuple[str, dt.datetime]: ...

    def decode_access(self, token: str) -> AccessClaims: ...


class JWTTokenIssuer:
    def _config(self) -> dict[str, Any]:
        return university_settings.get("AUTH.JWT")

    def _signing_key(self) -> str:
        return self._config().get("SIGNING_KEY") or keyed_hash(settings.SECRET_KEY, purpose="jwt-signing-key")

    def _verifying_key(self) -> str:
        cfg = self._config()
        if cfg["ALGORITHM"].startswith("HS"):
            return self._signing_key()
        if not cfg.get("VERIFYING_KEY"):
            raise exceptions.AuthenticationFailed("Token verification is misconfigured.")
        return cfg["VERIFYING_KEY"]

    def issue_access(self, *, user: Any, session: Any) -> tuple[str, dt.datetime]:
        cfg = self._config()
        now = timezone.now()
        expires = now + dt.timedelta(seconds=int(cfg["ACCESS_TOKEN_LIFETIME_SECONDS"]))
        payload: dict[str, Any] = {
            "iss": cfg["ISSUER"],
            "sub": str(user.pk),
            "sid": str(session.pk),
            "jti": uuid.uuid4().hex,
            "iat": int(now.timestamp()),
            "nbf": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "typ": "access",
            "stm": stamp_fingerprint(user.security_stamp),
        }
        if cfg.get("AUDIENCE"):
            payload["aud"] = cfg["AUDIENCE"]
        token = jwt.encode(payload, self._signing_key(), algorithm=cfg["ALGORITHM"])
        return token, expires

    def decode_access(self, token: str) -> AccessClaims:
        cfg = self._config()
        try:
            payload = jwt.decode(
                token,
                self._verifying_key(),
                algorithms=[cfg["ALGORITHM"]],
                audience=cfg.get("AUDIENCE"),
                issuer=cfg["ISSUER"],
                leeway=int(cfg.get("LEEWAY_SECONDS", 0)),
                options={"require": ["exp", "iat", "sub", "sid", "iss", "jti"]},
            )
        except jwt.ExpiredSignatureError:
            raise exceptions.AuthenticationFailed("The access token has expired.", code="token_expired") from None
        except jwt.InvalidTokenError:
            raise exceptions.AuthenticationFailed("Invalid access token.", code="token_invalid") from None
        if payload.get("typ") != "access":
            raise exceptions.AuthenticationFailed("Invalid access token.", code="token_invalid")
        return AccessClaims(
            user_id=str(payload["sub"]),
            session_id=str(payload["sid"]),
            stamp=str(payload.get("stm", "")),
            token_id=str(payload["jti"]),
            issued_at=dt.datetime.fromtimestamp(payload["iat"], tz=dt.UTC),
            expires_at=dt.datetime.fromtimestamp(payload["exp"], tz=dt.UTC),
        )


def get_token_issuer() -> TokenIssuer:
    return university_settings.import_from("AUTH.TOKEN_ISSUER")()
