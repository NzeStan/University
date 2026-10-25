"""Namespaced, lazily resolved settings for University Core and its modules.

All University configuration lives in a single ``UNIVERSITY`` Django setting.
Core reads the top-level keys declared in :mod:`university.core.defaults`;
each optional module reads its own namespace::

    UNIVERSITY = {
        "AUTH": {...},            # Core
        "INSTITUTION": {...},     # university-institution
    }

Usage::

    from university.core.conf import university_settings

    university_settings.AUTH["JWT"]["ALGORITHM"]
    university_settings.get("AUTH.JWT.ALGORITHM")
    university_settings.import_from("PROVIDERS.EMAIL")   # -> class

Settings are reloaded automatically when ``UNIVERSITY`` changes (for example
under ``override_settings`` in tests).
"""

from __future__ import annotations

import copy
import weakref
from collections.abc import Mapping
from typing import Any

from django.conf import settings
from django.core.exceptions import ImproperlyConfigured
from django.core.signals import setting_changed
from django.utils.module_loading import import_string

from university.core.defaults import DEFAULTS

SETTINGS_NAME = "UNIVERSITY"

_MISSING = object()
_instances: weakref.WeakSet[ModuleSettings] = weakref.WeakSet()


def deep_merge(base: Mapping[str, Any], override: Mapping[str, Any]) -> dict[str, Any]:
    """Recursively merge ``override`` into a deep copy of ``base``.

    Nested mappings are merged; every other value (including lists) in
    ``override`` replaces the value in ``base``.
    """
    result = copy.deepcopy(dict(base))
    for key, value in override.items():
        current = result.get(key)
        if isinstance(value, Mapping) and isinstance(current, Mapping):
            result[key] = deep_merge(current, value)
        else:
            result[key] = copy.deepcopy(value)
    return result


def get_user_settings() -> Mapping[str, Any]:
    """Return the raw ``UNIVERSITY`` setting, validated to be a mapping."""
    value = getattr(settings, SETTINGS_NAME, None) or {}
    if not isinstance(value, Mapping):
        raise ImproperlyConfigured(f"settings.{SETTINGS_NAME} must be a dict.")
    return value


class ModuleSettings:
    """Settings accessor for one namespace of the ``UNIVERSITY`` setting.

    :param namespace: Top-level key owned by a module (``"INSTITUTION"``), or
        ``None`` for Core, which owns the keys present in its defaults.
    :param defaults: Default values; user values are deep-merged over them.
    """

    def __init__(self, namespace: str | None, defaults: Mapping[str, Any]) -> None:
        self.namespace = namespace
        self.defaults = defaults
        self._data: dict[str, Any] | None = None
        self._imports: dict[str, Any] = {}
        _instances.add(self)

    # -- loading ---------------------------------------------------------
    @property
    def data(self) -> dict[str, Any]:
        if self._data is None:
            user = get_user_settings()
            if self.namespace is None:
                overrides = {k: v for k, v in user.items() if k in self.defaults}
            else:
                overrides = user.get(self.namespace) or {}
                if not isinstance(overrides, Mapping):
                    raise ImproperlyConfigured(f"settings.{SETTINGS_NAME}[{self.namespace!r}] must be a dict.")
            self._data = deep_merge(self.defaults, overrides)
        return self._data

    def reload(self) -> None:
        self._data = None
        self._imports.clear()

    # -- access ----------------------------------------------------------
    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)
        try:
            return self.data[name]
        except KeyError:
            where = self.namespace or "core"
            raise AttributeError(f"Invalid University setting {name!r} ({where}).") from None

    def get(self, path: str, default: Any = _MISSING) -> Any:
        """Return a nested value by dotted path, e.g. ``"AUTH.JWT.ALGORITHM"``."""
        node: Any = self.data
        for part in path.split("."):
            if isinstance(node, Mapping) and part in node:
                node = node[part]
            elif default is not _MISSING:
                return default
            else:
                raise KeyError(f"Unknown University setting: {path}")
        return node

    def import_from(self, path: str) -> Any:
        """Resolve a dotted import path stored at ``path`` (cached)."""
        if path not in self._imports:
            value = self.get(path)
            if isinstance(value, str):
                try:
                    value = import_string(value)
                except ImportError as exc:
                    raise ImproperlyConfigured(
                        f"Could not import {value!r} for University setting {path}: {exc}"
                    ) from exc
            self._imports[path] = value
        return self._imports[path]


def _reload_on_change(*, setting: str, **kwargs: Any) -> None:
    if setting == SETTINGS_NAME:
        for instance in list(_instances):
            instance.reload()


setting_changed.connect(_reload_on_change, dispatch_uid="university.core.conf.reload")

#: Settings for University Core.
university_settings = ModuleSettings(None, DEFAULTS)

__all__ = [
    "SETTINGS_NAME",
    "ModuleSettings",
    "deep_merge",
    "get_user_settings",
    "university_settings",
]
