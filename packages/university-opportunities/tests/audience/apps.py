"""A stand-in audience module (like university-institution) for tests."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from university.core.declarations import ScopeTypeDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig

MEMBERS: dict[str, list[tuple[str, str]]] = {}


def memberships(user: Any) -> list[tuple[str, str]]:
    return MEMBERS.get(str(user.pk), [])


class AudienceConfig(UniversityAppConfig):
    name = "tests.audience"
    label = "test_audience"
    module_name = "test_audience"

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        return [ScopeTypeDef("institution"), ScopeTypeDef("campus"), ScopeTypeDef("community")]

    def register_hooks(self, hooks: HookRegistry) -> None:
        hooks.register(Hook.SCOPE_MEMBERSHIPS, memberships)
