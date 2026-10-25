from __future__ import annotations

from django.utils.translation import gettext_lazy as _

from university.core.events import EventBus
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.search import __version__


class SearchConfig(UniversityAppConfig):
    name = "university.search"
    label = "university_search"
    verbose_name = _("University Search")
    module_name = "search"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "SEARCH"
    api_prefix = "search/"
    api_urlconfs = {"v1": "university.search.api.v1.urls"}

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"search": "120/minute", "search_people": "30/minute"}

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.search.indexing import event_names, handle_event

        for name in event_names():
            bus.subscribe(name, handle_event)

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.search.indexing import purge_author

        hooks.register(Hook.USER_PURGE, purge_author)
