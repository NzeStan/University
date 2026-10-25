"""The University module registry.

The registry discovers every installed University module (any Django app
whose config inherits :class:`~university.core.modules.UniversityAppConfig`)
and aggregates what they contribute. It fails gracefully when optional
modules are absent::

    from university.core import registry

    if registry.is_installed("social"):
        ...
    registry.get("social")          # ModuleInfo or None
    registry.require("institution") # raises ModuleNotInstalled if missing

Lightweight plugins that need no models can also be distributed as plain
Python packages exposing an entry point in the ``university.plugins`` group.
The entry point must reference a callable accepting the registry.
"""

from __future__ import annotations

import fnmatch
import logging
import threading
from collections.abc import Callable, Iterator
from importlib import metadata
from typing import Any

from django.apps import apps
from django.core.exceptions import ImproperlyConfigured

from university.core.declarations import (
    PLATFORM_SCOPE,
    HealthCheck,
    ModuleInfo,
    PermissionDef,
    RetentionPolicy,
    RoleDef,
    ScopeTypeDef,
)
from university.core.exceptions import ModuleNotInstalled

logger = logging.getLogger("university.registry")


class Registry:
    """Discovers installed University modules and their contributions."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._modules: dict[str, ModuleInfo] | None = None
        self._configs: dict[str, Any] = {}
        self._permissions: dict[str, PermissionDef] = {}
        self._roles: dict[str, RoleDef] = {}
        self._scope_types: dict[str, ScopeTypeDef] = {}
        self._health_checks: dict[str, HealthCheck] = {}
        self._retention: dict[str, RetentionPolicy] = {}
        self._throttle_rates: dict[str, str | None] = {}
        self._content_adapters: dict[str, Any] = {}
        self._payable_adapters: dict[str, Any] = {}
        self._media_library: Any = None
        self._plugins: dict[str, Any] = {}
        self._extra_contributions: list[Callable[[Registry], None]] = []

    # ------------------------------------------------------------ discovery
    def _ensure_loaded(self) -> None:
        if self._modules is not None:
            return
        with self._lock:
            if self._modules is not None:
                return
            if not apps.ready and not apps.apps_ready:
                raise ImproperlyConfigured("The University registry requires Django apps to be loaded.")
            from university.core.modules import UniversityAppConfig

            modules: dict[str, ModuleInfo] = {}
            for config in apps.get_app_configs():
                if not isinstance(config, UniversityAppConfig) or not config.module_name:
                    continue
                if config.module_name in modules:
                    raise ImproperlyConfigured(f"Two installed apps declare University module {config.module_name!r}.")
                modules[config.module_name] = ModuleInfo(
                    name=config.module_name,
                    label=config.label,
                    app_name=config.name,
                    version=config.module_version,
                    verbose_name=str(config.verbose_name),
                    requires=tuple(config.module_requires),
                )
                self._configs[config.module_name] = config
            self._modules = modules
            self._scope_types[PLATFORM_SCOPE] = ScopeTypeDef(PLATFORM_SCOPE, "The whole platform.")
            for config in self._configs.values():
                self._collect(config)
            for contribute in self._extra_contributions:
                contribute(self)

    def _collect(self, config: Any) -> None:
        for perm in config.get_permissions():
            self.add_permission(perm, source=config.module_name)
        for role in config.get_roles():
            self.add_role(role, source=config.module_name)
        for scope in config.get_scope_types():
            self.add_scope_type(scope, source=config.module_name)
        for check in config.get_health_checks():
            self._health_checks[check.name] = check
        for policy in config.get_retention_policies():
            self._retention[policy.name] = policy
        self._throttle_rates.update(config.get_throttle_rates())
        for adapter in config.get_content_adapters():
            if adapter.content_type in self._content_adapters:
                raise ImproperlyConfigured(f"Content type {adapter.content_type!r} registered twice.")
            self._content_adapters[adapter.content_type] = adapter
        for adapter in config.get_payable_adapters():
            if adapter.purpose in self._payable_adapters:
                raise ImproperlyConfigured(f"Payable purpose {adapter.purpose!r} registered twice.")
            self._payable_adapters[adapter.purpose] = adapter
        library = config.get_media_library()
        if library is not None:
            if self._media_library is not None:
                raise ImproperlyConfigured("Two installed modules provide a media library.")
            self._media_library = library

    def _loaded(self) -> dict[str, ModuleInfo]:
        self._ensure_loaded()
        return self._modules or {}

    def reset(self) -> None:
        """Forget discovered state (for tests)."""
        with self._lock:
            self._modules = None
            self._configs.clear()
            self._permissions.clear()
            self._roles.clear()
            self._scope_types.clear()
            self._health_checks.clear()
            self._retention.clear()
            self._throttle_rates.clear()
            self._content_adapters.clear()
            self._payable_adapters.clear()
            self._media_library = None

    # ----------------------------------------------------------- modules
    def all(self) -> list[ModuleInfo]:
        return list(self._loaded().values())

    def __iter__(self) -> Iterator[ModuleInfo]:
        return iter(self.all())

    def get(self, name: str) -> ModuleInfo | None:
        return self._loaded().get(name)

    def is_installed(self, name: str) -> bool:
        return self.get(name) is not None

    def require(self, name: str) -> ModuleInfo:
        info = self.get(name)
        if info is None:
            raise ModuleNotInstalled(name)
        return info

    def get_config(self, name: str) -> Any:
        self.require(name)
        return self._configs[name]

    def configs(self) -> list[Any]:
        self._ensure_loaded()
        return list(self._configs.values())

    def missing_dependencies(self) -> dict[str, list[str]]:
        """Return ``{module: [missing required modules]}``."""
        result: dict[str, list[str]] = {}
        for info in self.all():
            missing = [dep for dep in info.requires if not self.is_installed(dep)]
            if missing:
                result[info.name] = missing
        return result

    # ------------------------------------------------------ contributions
    def contribute(self, fn: Callable[[Registry], None]) -> Callable[[Registry], None]:
        """Register a callable that adds contributions once modules load.

        Used by entry-point plugins that are not Django apps.
        """
        self._extra_contributions.append(fn)
        if self._modules is not None:
            fn(self)
        return fn

    def add_permission(self, perm: PermissionDef, *, source: str = "plugin") -> None:
        existing = self._permissions.get(perm.code)
        if existing is not None and existing != perm:
            raise ImproperlyConfigured(f"Permission {perm.code!r} declared twice (latest by {source}).")
        self._permissions[perm.code] = perm

    def add_role(self, role: RoleDef, *, source: str = "plugin") -> None:
        existing = self._roles.get(role.key)
        if existing is not None and existing != role:
            raise ImproperlyConfigured(f"Role {role.key!r} declared twice (latest by {source}).")
        self._roles[role.key] = role

    def add_scope_type(self, scope: ScopeTypeDef, *, source: str = "plugin") -> None:
        if scope.name in self._scope_types and scope.name != PLATFORM_SCOPE:
            raise ImproperlyConfigured(f"Scope type {scope.name!r} declared twice (latest by {source}).")
        self._scope_types[scope.name] = scope

    def add_health_check(self, check: HealthCheck) -> None:
        self._ensure_loaded()
        self._health_checks[check.name] = check

    def add_retention_policy(self, policy: RetentionPolicy) -> None:
        self._ensure_loaded()
        self._retention[policy.name] = policy

    @property
    def permissions(self) -> dict[str, PermissionDef]:
        self._ensure_loaded()
        return dict(self._permissions)

    def permission_exists(self, code: str) -> bool:
        """True if ``code`` (or wildcard pattern) matches a declared permission."""
        perms = self.permissions
        if any(ch in code for ch in "*?["):
            return any(fnmatch.fnmatchcase(p, code) for p in perms)
        return code in perms

    @property
    def roles(self) -> dict[str, RoleDef]:
        self._ensure_loaded()
        return dict(self._roles)

    @property
    def scope_types(self) -> dict[str, ScopeTypeDef]:
        self._ensure_loaded()
        return dict(self._scope_types)

    @property
    def health_checks(self) -> dict[str, HealthCheck]:
        self._ensure_loaded()
        return dict(self._health_checks)

    @property
    def retention_policies(self) -> dict[str, RetentionPolicy]:
        self._ensure_loaded()
        return dict(self._retention)

    @property
    def content_adapters(self) -> dict[str, Any]:
        """Content adapters contributed by modules, by content type."""
        self._ensure_loaded()
        return dict(self._content_adapters)

    @property
    def media_library(self) -> Any:
        """The media library contributed by a module (e.g. university-media), or ``None``."""
        self._ensure_loaded()
        return self._media_library

    @property
    def payable_adapters(self) -> dict[str, Any]:
        """Payable adapters contributed by modules, by purpose."""
        self._ensure_loaded()
        return dict(self._payable_adapters)

    @property
    def throttle_rates(self) -> dict[str, str | None]:
        """Module-contributed default throttle rates."""
        self._ensure_loaded()
        return dict(self._throttle_rates)

    # ------------------------------------------------------- entry points
    def load_entry_point_plugins(self, group: str, disabled: list[str]) -> None:
        """Load lightweight plugins advertised through package entry points."""
        try:
            entry_points = metadata.entry_points(group=group)
        except Exception:  # pragma: no cover - metadata backends vary
            logger.exception("Could not read entry points for group %s", group)
            return
        for ep in entry_points:
            if ep.name in disabled or ep.name in self._plugins:
                continue
            try:
                plugin = ep.load()
                if callable(plugin):
                    plugin(self)
                self._plugins[ep.name] = plugin
            except Exception:
                # A broken optional plugin must not take the platform down.
                logger.exception("Failed to load University plugin %r", ep.name)

    @property
    def plugins(self) -> list[str]:
        return list(self._plugins)


#: The process-wide registry.
registry = Registry()

get = registry.get
is_installed = registry.is_installed
require = registry.require

__all__ = ["Registry", "get", "is_installed", "registry", "require"]
