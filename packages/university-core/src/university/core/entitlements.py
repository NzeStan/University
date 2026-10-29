"""Premium features across modules.

A module offering paid features (university-subscriptions) implements
:data:`Hook.USER_ENTITLEMENTS`; a module gating a feature calls
:func:`has_entitlement` without depending on how it was bought::

    # university.subscriptions (provider)
    hooks.register(Hook.USER_ENTITLEMENTS, lambda user: ["creator.analytics_pro"])

    # university.creator (consumer)
    if has_entitlement(request.user, "creator.analytics_pro"): ...

Results are memoised on the user object for the duration of a request.
"""

from __future__ import annotations

import contextlib
from typing import Any

from university.core.hooks import Hook, hooks

_MEMO_ATTR = "_university_entitlements"


def entitlements(user: Any) -> frozenset[str]:
    """Entitlement keys ``user`` currently holds."""
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()
    memo = getattr(user, _MEMO_ATTR, None)
    if memo is not None:
        return memo
    keys = frozenset(str(key) for result in hooks.call(Hook.USER_ENTITLEMENTS, user) for key in (result or ()) if key)
    with contextlib.suppress(AttributeError):  # exotic user objects
        setattr(user, _MEMO_ATTR, keys)
    return keys


def has_entitlement(user: Any, key: str) -> bool:
    return key in entitlements(user)


def ensure_entitlement(user: Any, key: str) -> None:
    from university.core.exceptions import PermissionDenied

    if not has_entitlement(user, key):
        raise PermissionDenied("This is a premium feature.", code="premium_required")


def forget(user: Any) -> None:
    """Drop the memoised entitlements (after a subscription change)."""
    if hasattr(user, _MEMO_ATTR):
        delattr(user, _MEMO_ATTR)
