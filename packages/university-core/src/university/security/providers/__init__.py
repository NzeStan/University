"""External identity providers (OAuth2 / OpenID Connect).

Configure providers in ``UNIVERSITY["AUTH"]["IDENTITY_PROVIDERS"]``::

    "IDENTITY_PROVIDERS": {
        "google": {
            "CLASS": "university.security.providers.oidc.OIDCIdentityProvider",
            "OPTIONS": {
                "issuer": "https://accounts.google.com",
                "jwks_url": "https://www.googleapis.com/oauth2/v3/certs",
                "audience": "<client id>",
            },
        },
    }
"""

from __future__ import annotations

from typing import Any

from django.utils.module_loading import import_string

from university.core.conf import university_settings
from university.core.exceptions import NotFound
from university.security.providers.base import ExternalProfile, IdentityProvider

__all__ = ["ExternalProfile", "IdentityProvider", "get_identity_provider"]

_cache: dict[tuple[str, str], IdentityProvider] = {}


def get_identity_provider(key: str) -> IdentityProvider:
    config = (university_settings.get("AUTH.IDENTITY_PROVIDERS", {}) or {}).get(key)
    if not config:
        raise NotFound("Unknown identity provider.")
    cache_key = (key, config["CLASS"])
    if cache_key not in _cache:
        cls: Any = import_string(config["CLASS"])
        _cache[cache_key] = cls(key=key, **(config.get("OPTIONS") or {}))
    return _cache[cache_key]
