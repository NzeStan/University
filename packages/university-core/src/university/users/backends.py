"""Authentication backend.

Accepts any configured identifier (email, handle, verified phone) and keeps
response timing independent of whether the account exists. Only ``active``
users authenticate; expired suspensions are lifted lazily.
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend
from django.utils import timezone

from university.core.conf import university_settings
from university.users.constants import UserStatus
from university.users.validators import normalize_email, normalize_handle, normalize_phone


def find_user_by_identifier(identifier: str) -> Any:
    """Resolve a login identifier to a non-deleted user, or ``None``."""
    User = get_user_model()
    identifier = (identifier or "").strip()
    if not identifier:
        return None
    allowed = university_settings.get("AUTH.LOGIN_IDENTIFIERS", ["email"])
    qs = User.objects.all()
    if "@" in identifier and "email" in allowed:
        return qs.filter(email=normalize_email(identifier)).first()
    if identifier.startswith("+") and "phone" in allowed:
        return qs.filter(phone_number=normalize_phone(identifier), phone_verified_at__isnull=False).first()
    if "handle" in allowed:
        return qs.filter(handle=normalize_handle(identifier)).first()
    return None


def lift_expired_suspension(user: Any) -> bool:
    """Reactivate a suspended user whose suspension has ended."""
    if user.status == UserStatus.SUSPENDED and user.suspended_until and user.suspended_until <= timezone.now():
        user.status = UserStatus.ACTIVE
        user.suspended_until = None
        user.status_reason = ""
        user.status_changed_at = timezone.now()
        user.save(update_fields=["status", "suspended_until", "status_reason", "status_changed_at"])
        return True
    return False


class UniversityAuthBackend(ModelBackend):
    def authenticate(
        self,
        request: Any,
        username: str | None = None,
        password: str | None = None,
        identifier: str | None = None,
        **kwargs: Any,
    ) -> Any:
        identifier = identifier or username or kwargs.get(get_user_model().USERNAME_FIELD)
        if not identifier or password is None:
            return None
        user = find_user_by_identifier(identifier)
        if user is None:
            # Run the hasher anyway so timing does not reveal account existence.
            get_user_model()().set_password(password)
            return None
        lift_expired_suspension(user)
        if user.check_password(password) and self.user_can_authenticate(user):
            return user
        return None

    def user_can_authenticate(self, user: Any) -> bool:
        return getattr(user, "status", None) == UserStatus.ACTIVE
