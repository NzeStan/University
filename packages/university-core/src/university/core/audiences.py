"""Audience membership across modules.

Content can be restricted to an *audience scope* — an institution, a campus,
a community — without the content module knowing who defines that scope.
Membership modules implement :data:`Hook.SCOPE_MEMBERSHIPS`; consumers call
:func:`member_scopes`::

    # university.institution (provider)
    hooks.register(Hook.SCOPE_MEMBERSHIPS, lambda user: [("institution", "…uuid…")])

    # university.social (consumer)
    if ("institution", post.scope_id) in member_scopes(viewer): ...

Results are memoised on the user object for the duration of a request.
"""

from __future__ import annotations

import contextlib
from collections import defaultdict
from typing import Any

from university.core.hooks import Hook, hooks

_MEMO_ATTR = "_university_member_scopes"


def member_scopes(user: Any) -> frozenset[tuple[str, str]]:
    """``{(scope_type, scope_id)}`` audiences ``user`` belongs to."""
    if user is None or not getattr(user, "is_authenticated", False):
        return frozenset()
    memo = getattr(user, _MEMO_ATTR, None)
    if memo is not None:
        return memo
    scopes: set[tuple[str, str]] = set()
    for result in hooks.call(Hook.SCOPE_MEMBERSHIPS, user):
        for scope_type, scope_id in result or ():
            if scope_type and scope_id:
                scopes.add((str(scope_type), str(scope_id)))
    frozen = frozenset(scopes)
    with contextlib.suppress(AttributeError):  # exotic user objects
        setattr(user, _MEMO_ATTR, frozen)
    return frozen


def member_scopes_by_type(user: Any) -> dict[str, list[str]]:
    """Group :func:`member_scopes` as ``{scope_type: [ids]}`` (for queries)."""
    grouped: dict[str, list[str]] = defaultdict(list)
    for scope_type, scope_id in member_scopes(user):
        grouped[scope_type].append(scope_id)
    return dict(grouped)


def is_member(user: Any, scope_type: str, scope_id: Any) -> bool:
    return (scope_type, str(scope_id)) in member_scopes(user)


def can_post_to(user: Any, scope_type: str, scope_id: Any, content_type: str) -> bool:
    """Whether the audience allows ``user`` to post ``content_type`` into it.

    Membership is necessary but not sufficient: an audience provider may
    restrict posting (e.g. a community where only moderators post).
    """
    return hooks.allows(Hook.AUDIENCE_CAN_POST, user, scope_type, str(scope_id), content_type)


def ensure_can_post_to(user: Any, scope_type: str, scope_id: Any, content_type: str) -> None:
    from university.core.exceptions import PermissionDenied

    if not can_post_to(user, scope_type, scope_id, content_type):
        raise PermissionDenied("Posting here is limited to certain members.", code="audience_posting_restricted")


def forget(user: Any) -> None:
    """Drop the memoised memberships (after a membership change)."""
    if hasattr(user, _MEMO_ATTR):
        delattr(user, _MEMO_ATTR)
