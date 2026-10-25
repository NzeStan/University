"""Generic OpenID Connect ID-token provider (Google, Microsoft, Apple, Keycloak …).

The client completes the provider's sign-in flow and posts the resulting
``id_token`` (and the ``nonce`` it generated). The token is verified against
the provider's published JWKS: signature, issuer, audience, expiry and nonce.
Requires ``cryptography`` (``pip install 'university-core[oidc]'``).
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

import jwt

from university.core.crypto import constant_time_equals
from university.core.exceptions import AuthenticationFailed
from university.security.providers.base import ExternalProfile


class OIDCIdentityProvider:
    def __init__(
        self,
        *,
        key: str,
        issuer: str,
        audience: str | list[str],
        jwks_url: str,
        algorithms: Iterable[str] = ("RS256",),
        require_nonce: bool = True,
        allowed_email_domains: Iterable[str] = (),
        leeway: int = 30,
    ) -> None:
        self.key = key
        self.issuer = issuer
        self.audience = audience
        self.algorithms = list(algorithms)
        self.require_nonce = require_nonce
        self.allowed_email_domains = {d.lower() for d in allowed_email_domains}
        self.leeway = leeway
        self._jwks = jwt.PyJWKClient(jwks_url, cache_keys=True, lifespan=3600, timeout=10)

    def authenticate(self, credential: Mapping[str, Any]) -> ExternalProfile:
        failure = AuthenticationFailed("Unable to sign in with this provider.", code="external_auth_failed")
        id_token = credential.get("id_token")
        if not isinstance(id_token, str) or len(id_token) > 8192:
            raise failure
        try:
            signing_key = self._jwks.get_signing_key_from_jwt(id_token)
            claims = jwt.decode(
                id_token,
                signing_key.key,
                algorithms=self.algorithms,
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
        except (jwt.InvalidTokenError, jwt.PyJWKClientError):
            raise failure from None
        if self.require_nonce:
            nonce = credential.get("nonce")
            if not nonce or not constant_time_equals(str(claims.get("nonce", "")), str(nonce)):
                raise failure
        email = str(claims.get("email") or "").lower()
        if self.allowed_email_domains and email.rpartition("@")[2] not in self.allowed_email_domains:
            raise failure
        return ExternalProfile(
            subject=str(claims["sub"]),
            email=email,
            email_verified=bool(claims.get("email_verified")),
            display_name=str(claims.get("name") or "")[:100],
        )
