from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class ExternalProfile:
    """Identity asserted by an external provider after verification."""

    subject: str
    email: str = ""
    email_verified: bool = False
    display_name: str = ""


class IdentityProvider(Protocol):
    key: str

    def authenticate(self, credential: Mapping[str, Any]) -> ExternalProfile:
        """Verify a client-supplied credential (ID token, auth code …).

        Must raise :class:`~university.core.exceptions.AuthenticationFailed`
        when the credential is not valid.
        """
        ...
