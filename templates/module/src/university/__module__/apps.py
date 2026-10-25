from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _

from university.__module__ import __version__
from university.core.declarations import PermissionDef
from university.core.events import EventBus
from university.core.modules import UniversityAppConfig


class __Module__Config(UniversityAppConfig):
    name = "university.__module__"
    label = "university___module__"
    verbose_name = _("University __Module__")
    module_name = "__module__"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "__MODULE__"
    api_prefix = "__module__/"
    api_urlconfs = {"v1": "university.__module__.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [PermissionDef("__module__.items.create", "Create __module__ items.")]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"__module___item_create": "60/hour"}

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.__module__.handlers import on_user_deleted

        bus.subscribe("user.deleted", on_user_deleted)
