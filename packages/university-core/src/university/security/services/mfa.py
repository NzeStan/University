"""Enrolment and removal of one-time-code second factors."""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.events import publish
from university.core.exceptions import ValidationError
from university.security import events
from university.security.models import OTPChallenge
from university.security.services.otp import issue_otp, verify_otp
from university.security.services.sessions import revoke_user_sessions

ENROL_PURPOSE = "mfa_enrolment"


def start_mfa_enrolment(user: Any, *, channel: str) -> OTPChallenge:
    if channel not in university_settings.get("AUTH.MFA.CHANNELS", ["email", "sms"]):
        raise ValidationError(details={"channel": ["This channel is not available."]})
    if channel == "sms":
        if not (user.phone_number and user.phone_verified_at):
            raise ValidationError(details={"channel": ["Verify a phone number first."]})
        destination = user.phone_number
    else:
        destination = user.email
    return issue_otp(purpose=f"{ENROL_PURPOSE}:{channel}", channel=channel, destination=destination, user=user)


@transaction.atomic
def confirm_mfa_enrolment(
    user: Any, *, challenge_id: Any, code: str, channel: str, current_session: Any = None
) -> None:
    from university.users.services.preferences import get_security_settings

    verify_otp(challenge_id=challenge_id, code=code, purpose=f"{ENROL_PURPOSE}:{channel}", user=user)
    settings_obj = get_security_settings(user)
    settings_obj.mfa_enabled = True
    settings_obj.mfa_channel = channel
    settings_obj.mfa_enabled_at = timezone.now()
    settings_obj.save(update_fields=["mfa_enabled", "mfa_channel", "mfa_enabled_at", "updated_at"])
    # Sessions created before MFA was enabled did not pass a second factor.
    revoke_user_sessions(user, actor=user, reason="mfa_enabled", except_session_id=getattr(current_session, "pk", None))
    audit(AuditAction.MFA_ENABLED, actor=user, target=user, metadata={"channel": channel})
    publish(events.MFA_ENABLED, {"user_id": user.pk, "channel": channel}, actor=user)


@transaction.atomic
def disable_mfa(user: Any, *, password: str) -> None:
    from university.users.services.preferences import get_security_settings

    if user.has_usable_password() and not user.check_password(password or ""):
        raise ValidationError(details={"password": ["Incorrect password."]}, code="invalid_password")
    settings_obj = get_security_settings(user)
    if not settings_obj.mfa_enabled:
        return
    settings_obj.mfa_enabled = False
    settings_obj.mfa_enabled_at = None
    settings_obj.save(update_fields=["mfa_enabled", "mfa_enabled_at", "updated_at"])
    audit(AuditAction.MFA_DISABLED, actor=user, target=user)
    publish(events.MFA_DISABLED, {"user_id": user.pk}, actor=user)
