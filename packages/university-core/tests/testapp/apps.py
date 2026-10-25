from __future__ import annotations

from collections.abc import Iterable
from typing import Any

from university.core.declarations import HealthCheck, PermissionDef, RoleDef, ScopeTypeDef
from university.core.events import EventBus
from university.core.hooks import HookRegistry
from university.core.modules import UniversityAppConfig

RECEIVED_EVENTS: list[Any] = []


def club_parents(club_id: Any) -> list[tuple[str, Any]]:
    # Clubs belong to a "school" scope encoded in their id for testing.
    from tests.testapp.state import CLUB_PARENTS

    parent = CLUB_PARENTS.get(str(club_id))
    return [("school", parent)] if parent else []


class TestAppConfig(UniversityAppConfig):
    name = "tests.testapp"
    label = "testapp"
    module_name = "testapp"
    module_version = "9.9.9"
    module_requires = ("core", "permissions")
    api_prefix = "testapp/"
    api_urlconfs = {"v1": "tests.testapp.urls"}
    settings_namespace = "TESTAPP"

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("testapp.widgets.view", "View widgets.", scopes=("platform", "school", "club")),
            PermissionDef("testapp.widgets.edit", "Edit widgets.", scopes=("platform", "school", "club")),
            PermissionDef("testapp.secret", "Sensitive.", sensitive=True),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef("school_editor", "School editor", "school", ("testapp.widgets.*",)),
            RoleDef("club_viewer", "Club viewer", "club", ("testapp.widgets.view",)),
            RoleDef("widget_viewer", "Widget viewer", "platform", ("testapp.widgets.view",)),
        ]

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        return [ScopeTypeDef("school"), ScopeTypeDef("club", parent_resolver=club_parents)]

    def get_health_checks(self) -> Iterable[HealthCheck]:
        from tests.testapp import state

        return [HealthCheck("testapp", lambda: state.HEALTHY)]

    def register_event_handlers(self, bus: EventBus) -> None:
        bus.subscribe("testapp.*", RECEIVED_EVENTS.append)

    def register_hooks(self, hooks: HookRegistry) -> None:
        pass
