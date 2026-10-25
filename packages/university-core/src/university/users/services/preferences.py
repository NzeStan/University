from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db import IntegrityError, transaction

from university.core.conf import university_settings
from university.users.models import NotificationSettings, PrivacySettings, SecuritySettings


def _get_or_create(model: type, user: Any, **defaults: Any) -> Any:
    try:
        with transaction.atomic():
            obj, _ = model.objects.get_or_create(user=user, defaults=defaults)
    except IntegrityError:  # concurrent creation
        obj = model.objects.get(user=user)
    return obj


def get_privacy_settings(user: Any) -> PrivacySettings:
    return _get_or_create(
        PrivacySettings,
        user,
        profile_visibility=university_settings.get("USERS.DEFAULT_PROFILE_VISIBILITY", "public"),
    )


def get_notification_settings(user: Any) -> NotificationSettings:
    return _get_or_create(NotificationSettings, user)


def get_security_settings(user: Any) -> SecuritySettings:
    return _get_or_create(SecuritySettings, user)


def ensure_user_settings(user: Any) -> None:
    get_privacy_settings(user)
    get_notification_settings(user)
    get_security_settings(user)


def update_settings(instance: Any, data: Mapping[str, Any]) -> Any:
    """Apply already-validated fields to a settings object."""
    changed = [field for field, value in data.items() if getattr(instance, field) != value]
    for field in changed:
        setattr(instance, field, data[field])
    if changed:
        instance.save(update_fields=[*changed, "updated_at"])
    return instance
