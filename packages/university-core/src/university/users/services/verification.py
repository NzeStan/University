from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.events import publish
from university.core.exceptions import ValidationError
from university.core.providers.email import send_templated_email
from university.core.ratelimit import rate_limit
from university.users import events
from university.users.constants import UserStatus
from university.users.tokens import (
    InvalidToken,
    email_matches,
    make_email_verification_token,
    read_email_verification_token,
)
from university.users.validators import normalize_email, normalize_phone, validate_phone

PHONE_VERIFICATION_PURPOSE = "phone_verification"


def _frontend_url(name: str, **params: str) -> str:
    template = university_settings.get(f"USERS.FRONTEND_URLS.{name}")
    return template.format(**params)


def send_verification_email(user: Any) -> None:
    token = make_email_verification_token(user)
    send_templated_email(
        "university/users/email/verify_email",
        {"display_name": user.get_short_name(), "url": _frontend_url("VERIFY_EMAIL", token=token)},
        [user.email],
    )


def resend_verification_email(email: str) -> None:
    """Resend the verification link. Always succeeds silently (no enumeration)."""
    email = normalize_email(email)
    rate_limit("email_verification", key=f"resend:{email}")
    user = get_user_model().objects.filter(email=email, email_verified_at__isnull=True).first()
    if user is not None and user.status in (UserStatus.PENDING, UserStatus.ACTIVE):
        send_verification_email(user)


@transaction.atomic
def verify_email(token: str) -> Any:
    try:
        data = read_email_verification_token(token)
    except InvalidToken:
        raise ValidationError("This verification link is invalid or has expired.", code="invalid_token") from None
    user = get_user_model().objects.select_for_update().filter(pk=data["u"]).first()
    if user is None or not email_matches(data["e"], user.email):
        raise ValidationError("This verification link is invalid or has expired.", code="invalid_token")
    if user.status not in (UserStatus.PENDING, UserStatus.ACTIVE):
        raise ValidationError("This verification link is invalid or has expired.", code="invalid_token")
    if user.email_verified_at is None:
        fields = ["email_verified_at"]
        user.email_verified_at = timezone.now()
        if user.status == UserStatus.PENDING:
            user.status = UserStatus.ACTIVE
            user.status_changed_at = timezone.now()
            fields += ["status", "status_changed_at"]
        user.save(update_fields=fields)
        audit(AuditAction.EMAIL_VERIFIED, actor=user, target=user)
        publish(events.USER_VERIFIED, {"user_id": user.pk}, actor=user)
    return user


def request_phone_verification(user: Any, phone_number: str) -> Any:
    """Send a one-time code to ``phone_number``; returns the OTP challenge."""
    from university.security.services.otp import issue_otp

    phone = normalize_phone(phone_number)
    try:
        validate_phone(phone)
    except Exception:
        raise ValidationError(details={"phone_number": ["Enter a valid international phone number."]}) from None
    return issue_otp(purpose=PHONE_VERIFICATION_PURPOSE, channel="sms", destination=phone, user=user)


@transaction.atomic
def confirm_phone_verification(user: Any, *, phone_number: str, challenge_id: Any, code: str) -> Any:
    from university.security.services.otp import verify_otp

    phone = normalize_phone(phone_number)
    verify_otp(challenge_id=challenge_id, code=code, purpose=PHONE_VERIFICATION_PURPOSE, user=user, destination=phone)
    user.phone_number = phone
    user.phone_verified_at = timezone.now()
    try:
        with transaction.atomic():
            user.save(update_fields=["phone_number", "phone_verified_at"])
    except IntegrityError:
        # Already verified on another account. Do not reveal which.
        raise ValidationError("Unable to verify this phone number.", code="phone_unavailable") from None
    audit(AuditAction.PHONE_VERIFIED, actor=user, target=user)
    publish(events.USER_PHONE_VERIFIED, {"user_id": user.pk}, actor=user)
    return user
