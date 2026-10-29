"""Privacy services: consent records and data portability."""

from __future__ import annotations

from typing import Any

from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.exceptions import ValidationError
from university.core.hooks import Hook, hooks
from university.core.http import ClientMeta, storable_ip
from university.core.serialization import to_jsonable
from university.users.models import ConsentRecord
from university.users.services.avatars import avatar_url


def record_consent(
    user: Any, *, purpose: str, granted: bool, version: str = "", meta: ClientMeta | None = None, source: str = "api"
) -> ConsentRecord:
    allowed = university_settings.get("USERS.CONSENT_PURPOSES", [])
    if purpose not in allowed:
        raise ValidationError(details={"purpose": [f"Unknown consent purpose {purpose!r}."]})
    consent = ConsentRecord.objects.create(
        user=user,
        purpose=purpose,
        granted=bool(granted),
        version=version[:32],
        source=source[:32],
        ip_address=storable_ip(meta.ip_address) if meta else None,
    )
    audit(AuditAction.CONSENT_RECORDED, actor=user, target=consent, metadata={"purpose": purpose, "granted": granted})
    return consent


def current_consents(user: Any) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for consent in ConsentRecord.objects.filter(user=user).order_by("-created_at"):
        latest.setdefault(
            consent.purpose,
            {"granted": consent.granted, "version": consent.version, "recorded_at": consent.created_at},
        )
    return latest


def _settings_dict(obj: Any, exclude: tuple[str, ...] = ("id", "user", "created_at")) -> dict[str, Any]:
    return {f.name: getattr(obj, f.name) for f in obj._meta.concrete_fields if f.name not in exclude}


def export_user_data(user: Any) -> dict[str, Any]:
    """Machine-readable copy of the user's personal data from every module."""
    from university.users.services.preferences import (
        get_notification_settings,
        get_privacy_settings,
        get_security_settings,
    )

    data: dict[str, Any] = {
        "generated_at": timezone.now(),
        "account": {
            "id": user.pk,
            "email": user.email,
            "handle": user.handle,
            "display_name": user.display_name,
            "avatar_url": avatar_url(user),
            "phone_number": user.phone_number,
            "email_verified_at": user.email_verified_at,
            "phone_verified_at": user.phone_verified_at,
            "status": user.status,
            "locale": user.locale,
            "timezone": user.timezone,
            "created_at": user.created_at,
            "last_login": user.last_login,
        },
        "privacy_settings": _settings_dict(get_privacy_settings(user)),
        "notification_settings": _settings_dict(get_notification_settings(user)),
        "security_settings": _settings_dict(get_security_settings(user)),
        "consents": [
            {"purpose": c.purpose, "granted": c.granted, "version": c.version, "recorded_at": c.created_at}
            for c in user.consents.all()
        ],
    }
    data.update(hooks.collect(Hook.USER_EXPORT_DATA, user))
    audit(AuditAction.DATA_EXPORTED, actor=user, target=user)
    return to_jsonable(data)
