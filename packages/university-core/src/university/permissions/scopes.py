"""Permission scopes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from university.core.declarations import PLATFORM_SCOPE


@dataclass(frozen=True)
class Scope:
    """Where a permission applies: ``Scope("institution", <uuid>)``.

    The platform scope has no id and contains every other scope.
    """

    type: str
    id: str = ""

    def __init__(self, type: str, id: Any = "") -> None:
        object.__setattr__(self, "type", type)
        object.__setattr__(self, "id", "" if id is None else str(id))

    @classmethod
    def platform(cls) -> Scope:
        return cls(PLATFORM_SCOPE, "")

    @property
    def is_platform(self) -> bool:
        return self.type == PLATFORM_SCOPE

    def key(self) -> str:
        return f"{self.type}:{self.id}"

    def __str__(self) -> str:
        return self.type if self.is_platform else f"{self.type}:{self.id}"


PLATFORM = Scope.platform()
