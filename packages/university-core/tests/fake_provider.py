from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from university.core.exceptions import AuthenticationFailed
from university.security.providers.base import ExternalProfile


class FakeProvider:
    """Accepts ``id_token="<email>|<subject>"`` (tests only)."""

    def __init__(self, *, key: str) -> None:
        self.key = key

    def authenticate(self, credential: Mapping[str, Any]) -> ExternalProfile:
        token = str(credential.get("id_token", ""))
        if "|" not in token:
            raise AuthenticationFailed(code="external_auth_failed")
        email, subject = token.split("|", 1)
        return ExternalProfile(subject=subject, email=email, email_verified=True, display_name="Fake")
