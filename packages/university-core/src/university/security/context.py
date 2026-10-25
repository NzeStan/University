"""What ``request.auth`` holds for University authentication classes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class AuthContext:
    method: str
    session: Any = None
    api_key: Any = None
    claims: Any = None

    @property
    def session_id(self) -> Any:
        return getattr(self.session, "pk", None)

    @property
    def is_api_key(self) -> bool:
        return self.api_key is not None
