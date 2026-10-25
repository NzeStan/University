"""Declarative types modules use to describe what they contribute.

These are plain, immutable data classes with no Django model dependencies so
that any module can declare permissions, roles, scope types, retention
policies and health checks without importing another module's internals.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

PLATFORM_SCOPE = "platform"


@dataclass(frozen=True)
class PermissionDef:
    """A permission a module exposes, e.g. ``"institution.memberships.verify"``.

    :param scopes: Scope types the permission is meaningful in. A grant at the
        ``platform`` scope always applies everywhere.
    :param sensitive: Marks permissions guarding privacy-critical operations
        (e.g. revealing anonymous authors). Surfaced in admin and docs.
    """

    code: str
    description: str
    scopes: tuple[str, ...] = (PLATFORM_SCOPE,)
    sensitive: bool = False


@dataclass(frozen=True)
class RoleDef:
    """A system role seeded into the database by ``post_migrate``.

    Permission entries may use shell-style wildcards (``"institution.*"``).
    """

    key: str
    name: str
    scope_type: str
    permissions: tuple[str, ...]
    description: str = ""


@dataclass(frozen=True)
class ScopeTypeDef:
    """A permission scope type contributed by a module.

    :param parent_resolver: Given a scope id, return ``(scope_type, scope_id)``
        pairs of the scopes that contain it (e.g. campus -> institution), so
        that grants on a parent scope apply to its children.
    """

    name: str
    description: str = ""
    parent_resolver: Callable[[Any], Iterable[tuple[str, Any]]] | None = None


@dataclass(frozen=True)
class RetentionPolicy:
    """A data-retention rule executed by ``manage.py university_purge``.

    :param setting: Human-readable name of the setting that controls it.
    :param cutoff: Returns the datetime before which data is purged, or None
        to skip (retention disabled).
    :param purge: Deletes/anonymises data older than the cutoff and returns
        the number of affected records. Receives ``dry_run``.
    """

    name: str
    description: str
    setting: str
    cutoff: Callable[[], datetime | None]
    purge: Callable[[datetime, bool], int]


@dataclass(frozen=True)
class HealthCheck:
    """A readiness check. ``check`` raises (or returns False) when unhealthy."""

    name: str
    check: Callable[[], bool | None]
    critical: bool = True


@dataclass(frozen=True)
class ModuleInfo:
    """Public description of an installed University module."""

    name: str
    label: str
    app_name: str
    version: str
    verbose_name: str
    requires: tuple[str, ...] = field(default_factory=tuple)
