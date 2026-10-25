"""Read-side queries for users, enforcing visibility rules.

Profiles that do not exist and profiles the viewer may not see produce the
same ``NotFound`` — callers cannot distinguish them (no enumeration).
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from university.core.exceptions import NotFound
from university.core.hooks import Hook, hooks
from university.permissions.services import has_permission
from university.users.constants import ProfileVisibility, UserStatus
from university.users.services.preferences import get_privacy_settings
from university.users.validators import normalize_handle


def can_view_profile(viewer: Any, target: Any) -> bool:
    if target.status != UserStatus.ACTIVE:
        return False
    authenticated = bool(viewer is not None and getattr(viewer, "is_authenticated", False))
    if authenticated and viewer.pk == target.pk:
        return True
    if authenticated and has_permission(viewer, "users.view_private"):
        return True
    privacy = get_privacy_settings(target)
    if privacy.profile_visibility == ProfileVisibility.PRIVATE:
        return False
    if privacy.profile_visibility == ProfileVisibility.MEMBERS and not authenticated:
        return False
    return hooks.allows(Hook.USER_CAN_VIEW_PROFILE, viewer if authenticated else None, target)


def get_visible_user(*, viewer: Any, user_id: Any = None, handle: str | None = None) -> Any:
    qs = get_user_model().objects.filter(status=UserStatus.ACTIVE)
    if user_id is not None:
        user = qs.filter(pk=user_id).first()
    elif handle:
        user = qs.filter(handle=normalize_handle(handle)).first()
    else:
        user = None
    if user is None or not can_view_profile(viewer, user):
        raise NotFound("User not found.")
    return user


def public_profile_extras(target: Any, viewer: Any) -> dict[str, Any]:
    """Module-contributed profile sections (memberships, counts …)."""
    return hooks.collect(Hook.USER_PUBLIC_PROFILE, target, viewer)
