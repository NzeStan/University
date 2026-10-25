"""Content adapter for user accounts (reporting a profile or account).

Profiles can be reported and their owners warned, restricted, suspended or
banned; content actions (hide/remove) don't apply to accounts.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model

from university.core.content import ContentAdapter, ContentRef
from university.core.exceptions import ValidationError
from university.core.ids import is_valid_uuid


class UserAccountAdapter(ContentAdapter):
    content_type = "users.user"
    moderatable = True
    label = "Account"

    def _get(self, object_id: Any) -> Any:
        if not is_valid_uuid(object_id):
            return None
        return get_user_model().objects.filter(pk=object_id).first()

    def resolve(self, object_id: Any) -> ContentRef | None:
        user = self._get(object_id)
        if user is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(user.pk),
            author_id=str(user.pk),
            excerpt=" ".join(filter(None, [f"@{user.handle}" if user.handle else "", user.display_name])),
            status=user.status,
            created_at=user.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.users.selectors import can_view_profile

        user = self._get(object_id)
        return user is not None and can_view_profile(viewer, user)

    def _unsupported(self) -> None:
        raise ValidationError("Accounts can't be hidden or removed; act on the account instead.", code="not_supported")

    def hide(self, object_id: Any, *, reason: str) -> None:
        self._unsupported()

    def remove(self, object_id: Any, *, reason: str) -> None:
        self._unsupported()

    def restore(self, object_id: Any) -> None:
        return None
