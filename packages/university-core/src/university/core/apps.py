from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _

from university.core import __version__
from university.core.declarations import RetentionPolicy
from university.core.modules import UniversityAppConfig


class CoreConfig(UniversityAppConfig):
    name = "university.core"
    label = "university_core"
    verbose_name = _("University Core")
    module_name = "core"
    module_version = __version__
    module_requires = ()
    api_urlconfs = {"v1": "university.core.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        from university.core import checks  # noqa: F401  (registers system checks)
        from university.core.conf import university_settings
        from university.core.registry import registry

        if university_settings.get("TASKS.BACKEND", "").endswith("CeleryTaskBackend"):
            from university.core.integrations import celery  # noqa: F401

        if university_settings.get("PLUGINS.LOAD_ENTRY_POINTS", True):
            registry.load_entry_point_plugins(
                university_settings.get("PLUGINS.ENTRY_POINT_GROUP", "university.plugins"),
                list(university_settings.get("PLUGINS.DISABLED", [])),
            )

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import core_retention_policies

        return core_retention_policies()
