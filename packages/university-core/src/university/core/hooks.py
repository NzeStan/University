"""Synchronous extension hooks.

Events (:mod:`university.core.events`) announce that something *happened*.
Hooks let modules *participate in a decision or a result* while it is being
computed — for example the social module vetoes profile visibility when the
viewer is blocked, or each module contributes a section to a data export.

Hook semantics:

* :meth:`HookRegistry.allows` — veto: every implementation must not return
  ``False``. Use for authorisation-style questions.
* :meth:`HookRegistry.collect` — merge the dict results of all implementations.
* :meth:`HookRegistry.call` — call all implementations and return results.

Implementations run in ascending ``priority`` order.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any


class Hook:
    """Names of hooks provided by Core. Modules may define their own."""

    #: (viewer, target) -> bool | None. Return False to hide a profile.
    USER_CAN_VIEW_PROFILE = "users.can_view_profile"
    #: (actor, target, action: str) -> bool | None. Return False to block an
    #: interaction (follow, mention, message, comment …).
    USER_CAN_INTERACT = "users.can_interact"
    #: (target, viewer) -> dict merged into the public profile representation.
    USER_PUBLIC_PROFILE = "users.public_profile"
    #: (user) -> dict of {section: data} merged into the user's data export.
    USER_EXPORT_DATA = "users.export_data"
    #: (user_id) -> None. Delete/anonymise module PII when a user is purged.
    USER_PURGE = "users.purge"
    #: (user, scope) -> iterable of permission codes granted implicitly
    #: (e.g. a community owner holds community permissions).
    PERMISSIONS_IMPLICIT_GRANTS = "permissions.implicit_grants"
    #: (user, code) -> iterable of (scope_type, scope_id) where ``code`` is
    #: implicitly granted. Mirrors PERMISSIONS_IMPLICIT_GRANTS for list
    #: filtering (e.g. a community moderator's moderation queue).
    PERMISSIONS_IMPLICIT_SCOPES = "permissions.implicit_scopes"
    #: (user) -> iterable of (scope_type, scope_id) audiences the user belongs
    #: to (verified institution members, campus members, community members …).
    #: Used for audience-restricted content without coupling modules.
    SCOPE_MEMBERSHIPS = "scopes.memberships"
    #: (user, content_type: str) -> bool | None. Return False to stop a user
    #: creating content of that type (e.g. a moderation restriction).
    USER_CAN_CREATE_CONTENT = "content.can_create"
    #: (user, scope_type, scope_id, content_type) -> bool | None. Return False
    #: to stop a user posting into an audience (e.g. a moderators-only community).
    AUDIENCE_CAN_POST = "audience.can_post"
    #: (content_type: str, object_ids: list[str]) -> dict[str, float]. Trending
    #: scores for content (e.g. from university-trending); feeds may rank by them.
    CONTENT_TRENDING_SCORES = "content.trending_scores"


@dataclass(frozen=True)
class _Impl:
    fn: Callable[..., Any]
    priority: int


class HookRegistry:
    def __init__(self) -> None:
        self._hooks: dict[str, list[_Impl]] = {}
        self._lock = threading.Lock()

    def register(self, name: str, fn: Callable[..., Any] | None = None, *, priority: int = 100) -> Any:
        """Register ``fn`` for hook ``name``. Usable as a decorator."""

        def decorator(func: Callable[..., Any]) -> Callable[..., Any]:
            with self._lock:
                impls = self._hooks.setdefault(name, [])
                if all(impl.fn is not func for impl in impls):
                    impls.append(_Impl(func, priority))
                    impls.sort(key=lambda impl: impl.priority)
            return func

        return decorator(fn) if fn is not None else decorator

    def unregister(self, name: str, fn: Callable[..., Any]) -> None:
        with self._lock:
            self._hooks[name] = [impl for impl in self._hooks.get(name, []) if impl.fn is not fn]

    def get(self, name: str) -> list[Callable[..., Any]]:
        return [impl.fn for impl in self._hooks.get(name, [])]

    def call(self, name: str, *args: Any, **kwargs: Any) -> list[Any]:
        return [fn(*args, **kwargs) for fn in self.get(name)]

    def allows(self, name: str, *args: Any, **kwargs: Any) -> bool:
        """True unless an implementation returns exactly ``False``."""
        return all(fn(*args, **kwargs) is not False for fn in self.get(name))

    def collect(self, name: str, *args: Any, **kwargs: Any) -> dict[str, Any]:
        merged: dict[str, Any] = {}
        for result in self.call(name, *args, **kwargs):
            if result:
                merged.update(result)
        return merged


#: The process-wide hook registry.
hooks = HookRegistry()

__all__ = ["Hook", "HookRegistry", "hooks"]
