"""Self-service account changes: profile, password, email, phone."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.contrib.auth.tokens import default_token_generator
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.encoding import force_bytes, force_str
from django.utils.http import urlsafe_base64_decode, urlsafe_base64_encode

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.events import publish
from university.core.exceptions import ValidationError
from university.core.providers.email import send_templated_email
from university.core.ratelimit import rate_limit
from university.users import events
from university.users.constants import UserStatus
from university.users.tokens import InvalidToken, email_matches, make_email_change_token, read_email_change_token
from university.users.validators import normalize_email, normalize_handle, validate_handle

#: Fields a user may change on their own profile.
PROFILE_FIELDS = ("handle", "display_name", "locale", "timezone")


def _frontend_url(name: str, **params: str) -> str:
    return university_settings.get(f"USERS.FRONTEND_URLS.{name}").format(**params)


def _check_password(user: Any, password: str) -> None:
    if not password or not user.check_password(password):
        raise ValidationError(details={"current_password": ["Incorrect password."]}, code="invalid_password")


def _validate_new_password(user: Any, password: str, field: str = "new_password") -> None:
    try:
        validate_password(password, user=user)
    except DjangoValidationError as exc:
        raise ValidationError(details={field: exc.messages}) from None


@transaction.atomic
def update_profile(user: Any, data: Mapping[str, Any]) -> Any:
    unknown = set(data) - set(PROFILE_FIELDS)
    if unknown:
        raise ValidationError(details={f: ["This field cannot be changed here."] for f in unknown})
    changed: list[str] = []
    if "handle" in data:
        handle = normalize_handle(data["handle"])
        if handle != user.handle:
            if handle is not None:
                try:
                    validate_handle(handle)
                except DjangoValidationError as exc:
                    raise ValidationError(details={"handle": exc.messages}) from None
            user.handle = handle
            changed.append("handle")
    for field in ("display_name", "locale", "timezone"):
        if field in data and getattr(user, field) != data[field]:
            setattr(user, field, (data[field] or "").strip())
            changed.append(field)
    if changed:
        try:
            with transaction.atomic():
                user.save(update_fields=[*changed, "updated_at"])
        except IntegrityError:
            raise ValidationError(details={"handle": ["This handle is not available."]}) from None
        publish(events.USER_UPDATED, {"user_id": user.pk, "fields": changed}, actor=user)
    return user


@transaction.atomic
def change_password(user: Any, *, current_password: str, new_password: str, current_session: Any = None) -> None:
    """Change the password and sign out every other session."""
    from university.security.services.sessions import revoke_user_sessions

    _check_password(user, current_password)
    _validate_new_password(user, new_password)
    user.set_password(new_password)
    user.rotate_security_stamp()
    user.save(update_fields=["password", "password_changed_at", "security_stamp"])
    if current_session is not None:
        # Keep the caller signed in under the new security stamp.
        type(current_session).objects.filter(pk=current_session.pk).update(security_stamp=user.security_stamp)
    revoke_user_sessions(
        user,
        actor=user,
        reason="password_changed",
        except_session_id=getattr(current_session, "pk", None),
    )
    audit(AuditAction.PASSWORD_CHANGED, actor=user, target=user)
    publish(events.USER_PASSWORD_CHANGED, {"user_id": user.pk}, actor=user)
    send_templated_email(
        "university/users/email/password_changed", {"display_name": user.get_short_name()}, [user.email]
    )


def request_password_reset(email: str) -> None:
    """Email a reset link if an active account exists. Never reveals existence."""
    email = normalize_email(email)
    rate_limit("password_reset", key=f"email:{email}")
    user = get_user_model().objects.filter(email=email, status=UserStatus.ACTIVE).first()
    if user is None or (not user.has_usable_password() and not user.email_verified):
        return
    uid = urlsafe_base64_encode(force_bytes(user.pk))
    token = default_token_generator.make_token(user)
    send_templated_email(
        "university/users/email/password_reset",
        {"display_name": user.get_short_name(), "url": _frontend_url("RESET_PASSWORD", uid=uid, token=token)},
        [user.email],
    )
    audit(AuditAction.PASSWORD_RESET_REQUESTED, actor=None, target=user)


@transaction.atomic
def confirm_password_reset(*, uid: str, token: str, new_password: str) -> Any:
    from university.security.services.sessions import revoke_user_sessions

    invalid = ValidationError("This reset link is invalid or has expired.", code="invalid_token")
    try:
        user_id = force_str(urlsafe_base64_decode(uid))
        user = get_user_model().objects.select_for_update().get(pk=user_id, status=UserStatus.ACTIVE)
    except (TypeError, ValueError, OverflowError, DjangoValidationError, get_user_model().DoesNotExist):
        raise invalid from None
    if not default_token_generator.check_token(user, token):
        raise invalid
    _validate_new_password(user, new_password)
    user.set_password(new_password)
    user.rotate_security_stamp()
    fields = ["password", "password_changed_at", "security_stamp"]
    if user.email_verified_at is None:
        # Following the emailed link proves control of the address.
        user.email_verified_at = timezone.now()
        fields.append("email_verified_at")
    user.save(update_fields=fields)
    revoke_user_sessions(user, actor=None, reason="password_reset")
    audit(AuditAction.PASSWORD_RESET_COMPLETED, actor=user, target=user)
    publish(events.USER_PASSWORD_CHANGED, {"user_id": user.pk, "via": "reset"}, actor=user)
    send_templated_email(
        "university/users/email/password_changed", {"display_name": user.get_short_name()}, [user.email]
    )
    return user


@transaction.atomic
def request_email_change(user: Any, *, new_email: str, password: str) -> None:
    """Start an email change; the new address must confirm it.

    Responds identically whether or not the new address is taken.
    """
    _check_password(user, password)
    new_email = normalize_email(new_email)
    if not new_email or new_email == user.email:
        raise ValidationError(details={"new_email": ["Enter a different email address."]})
    rate_limit("email_verification", key=f"change:{user.pk}")
    if get_user_model().all_objects.filter(email=new_email).exists():
        audit(AuditAction.EMAIL_CHANGE_REQUESTED, actor=user, target=user, outcome="failure")
        return
    user.pending_email = new_email
    user.save(update_fields=["pending_email"])
    token = make_email_change_token(user, new_email)
    send_templated_email(
        "university/users/email/confirm_email_change",
        {"display_name": user.get_short_name(), "url": _frontend_url("CONFIRM_EMAIL_CHANGE", token=token)},
        [new_email],
    )
    send_templated_email(
        "university/users/email/email_change_notice",
        {"display_name": user.get_short_name()},
        [user.email],
    )
    audit(AuditAction.EMAIL_CHANGE_REQUESTED, actor=user, target=user)


@transaction.atomic
def confirm_email_change(token: str) -> Any:
    invalid = ValidationError("This confirmation link is invalid or has expired.", code="invalid_token")
    try:
        data = read_email_change_token(token)
    except InvalidToken:
        raise invalid from None
    user = get_user_model().objects.select_for_update().filter(pk=data["u"], status=UserStatus.ACTIVE).first()
    if (
        user is None
        or not user.pending_email
        or not email_matches(data["e"], user.pending_email)
        or data.get("s") != user.security_stamp[:8]
    ):
        raise invalid
    old_email = user.email
    user.email = user.pending_email
    user.pending_email = ""
    user.email_verified_at = timezone.now()
    try:
        with transaction.atomic():
            user.save(update_fields=["email", "pending_email", "email_verified_at"])
    except IntegrityError:
        raise invalid from None
    audit(AuditAction.EMAIL_CHANGED, actor=user, target=user)
    publish(events.USER_EMAIL_CHANGED, {"user_id": user.pk}, actor=user)
    send_templated_email("university/users/email/email_changed", {"display_name": user.get_short_name()}, [old_email])
    return user


@transaction.atomic
def remove_phone_number(user: Any) -> Any:
    user.phone_number = None
    user.phone_verified_at = None
    user.save(update_fields=["phone_number", "phone_verified_at"])
    audit(AuditAction.PHONE_REMOVED, actor=user, target=user)
    return user
