"""Base ``AppConfig`` for every University module.

A University module is an ordinary Django app whose ``AppConfig`` inherits
:class:`UniversityAppConfig`. That single inheritance is the whole plugin
contract: the registry discovers the module, mounts its API routes, collects
its permissions, roles, scope types, health checks and retention policies,
and lets it subscribe to events and hooks — without Core knowing it exists.

Example::

    class SocialConfig(UniversityAppConfig):
        name = "university.social"
        label = "university_social"
        module_name = "social"
        module_version = __version__
        module_requires = ("core",)
        api_prefix = "social/"
        api_urlconfs = {"v1": "university.social.api.v1.urls"}

        def get_permissions(self):
            return [PermissionDef("social.posts.moderate", "Moderate posts")]

        def register_event_handlers(self, bus):
            bus.subscribe("user.deleted", hide_posts_of_deleted_user)
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from importlib import import_module
from typing import TYPE_CHECKING, Any, ClassVar

from django.apps import AppConfig
from django.utils.module_loading import module_has_submodule

from university.core.declarations import (
    HealthCheck,
    PermissionDef,
    RetentionPolicy,
    RoleDef,
    ScopeTypeDef,
)

if TYPE_CHECKING:
    from university.core.events import EventBus
    from university.core.hooks import HookRegistry


class UniversityAppConfig(AppConfig):
    """Base configuration for University modules."""

    default_auto_field = "django.db.models.BigAutoField"
    # Django auto-selects the single AppConfig in an ``apps.py``; importing this
    # base there would make two candidates. The base opts out and every
    # subclass opts back in (see __init_subclass__).
    default = False

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        if "default" not in cls.__dict__:
            cls.default = True

    #: Short, unique module name used by the registry (``"institution"``).
    module_name: ClassVar[str] = ""
    module_version: ClassVar[str] = "0.0.0"
    #: Names of modules that must also be installed.
    module_requires: ClassVar[tuple[str, ...]] = ("core",)
    #: Mount point under ``/api/<version>/`` (``""`` or ``"institutions/"``).
    api_prefix: ClassVar[str] = ""
    #: Map of API version -> dotted URLconf module path.
    api_urlconfs: ClassVar[Mapping[str, str]] = {}
    #: Top-level key this module owns in ``settings.UNIVERSITY`` (if any).
    settings_namespace: ClassVar[str | None] = None
    #: Submodules imported automatically on ready() when present.
    autodiscover_submodules: ClassVar[tuple[str, ...]] = ("tasks", "handlers")

    # -- lifecycle -------------------------------------------------------
    def ready(self) -> None:
        from university.core.events import event_bus
        from university.core.hooks import hooks

        for submodule in self.autodiscover_submodules:
            if module_has_submodule(self.module, submodule):
                import_module(f"{self.name}.{submodule}")
        self.register_event_handlers(event_bus)
        self.register_hooks(hooks)

    # -- contribution points (override as needed) -------------------------
    def get_api_urlconf(self, version: str) -> str | None:
        return self.api_urlconfs.get(version)

    def get_permissions(self) -> Iterable[PermissionDef]:
        return ()

    def get_roles(self) -> Iterable[RoleDef]:
        return ()

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        return ()

    def get_health_checks(self) -> Iterable[HealthCheck]:
        return ()

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        return ()

    def get_content_adapters(self) -> Iterable[Any]:
        """:class:`~university.core.content.ContentAdapter` instances for this module's content."""
        return ()

    def get_media_library(self) -> Any:
        """A :class:`~university.core.media.MediaLibrary` if this module stores media (one per deployment)."""
        return None

    def get_payable_adapters(self) -> Iterable[Any]:
        """:class:`~university.core.payables.PayableAdapter` instances for things this module sells."""
        return ()

    def get_throttle_rates(self) -> Mapping[str, str | None]:
        """Default rates for this module's throttle scopes.

        Deployments override them in ``UNIVERSITY["THROTTLE_RATES"]``.
        """
        return {}

    def register_event_handlers(self, bus: EventBus) -> None:
        """Subscribe to platform events. Called once from ``ready()``."""

    def register_hooks(self, hooks: HookRegistry) -> None:
        """Register hook implementations. Called once from ``ready()``."""
