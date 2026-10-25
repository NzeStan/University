"""Account registration.

Two modes (``USERS.REGISTRATION_MODE``):

``verify_first`` (default)
    Registration always answers the same way, whether or not the address is
    already registered. New accounts start ``pending`` and become ``active``
    when the emailed link is followed; the owner of an existing address gets
    a "someone tried to register" notice instead. Login is impossible until
    verification, so the response, the emails and login behaviour reveal
    nothing about which addresses have accounts.

``open``
    Accounts are active immediately and the API returns tokens. Duplicate
    addresses are rejected (revealing existence) — acceptable for closed or
    invite-only deployments.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model
from django.contrib.auth.password_validation import validate_password
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.events import publish
from university.core.exceptions import PermissionDenied, ValidationError
from university.core.http import ClientMeta
from university.core.providers.email import send_templated_email
from university.users import events
from university.users.constants import RegistrationMode, UserStatus
from university.users.services.data import record_consent
from university.users.services.preferences import ensure_user_settings
from university.users.services.verification import send_verification_email
from university.users.validators import normalize_email, normalize_handle, validate_handle


@dataclass(frozen=True)
class RegistrationResult:
    #: The new user, or ``None`` when the address was already registered
    #: ("verify_first" mode never tells the caller which).
    user: Any
    created: bool
    mode: str


def _validate_handle(handle: str | None) -> str | None:
    handle = normalize_handle(handle)
    if handle is None:
        return None
    try:
        validate_handle(handle)
    except DjangoValidationError as exc:
        raise ValidationError(details={"handle": exc.messages}) from None
    if get_user_model().all_objects.filter(handle=handle).exists():
        raise ValidationError(details={"handle": ["This handle is not available."]})
    return handle


def _validate_password(password: str, email: str, handle: str | None, display_name: str) -> None:
    probe = get_user_model()(email=email, handle=handle, display_name=display_name)
    try:
        validate_password(password, user=probe)
    except DjangoValidationError as exc:
        raise ValidationError(details={"password": exc.messages}) from None


def _notify_existing_account(email: str) -> None:
    existing = get_user_model().objects.filter(email=email).exclude(status=UserStatus.BANNED).first()
    if existing is not None:
        send_templated_email(
            "university/users/email/registration_existing_account",
            {"display_name": existing.get_short_name()},
            [existing.email],
        )
    audit(AuditAction.ACCOUNT_REGISTRATION_DUPLICATE, outcome="failure", target_type="user", metadata={})


def register_user(
    *,
    email: str,
    password: str,
    handle: str | None = None,
    display_name: str = "",
    consents: Mapping[str, bool] | None = None,
    consent_version: str = "",
    meta: ClientMeta | None = None,
) -> RegistrationResult:
    if not university_settings.get("USERS.ALLOW_REGISTRATION", True):
        raise PermissionDenied("Registration is currently closed.", code="registration_closed")
    mode = university_settings.get("USERS.REGISTRATION_MODE", RegistrationMode.VERIFY_FIRST)
    email = normalize_email(email)
    handle = _validate_handle(handle)
    _validate_password(password, email, handle, display_name)

    User = get_user_model()
    duplicate = User.all_objects.filter(email=email).exists()
    if not duplicate:
        try:
            with transaction.atomic():
                user = User.objects.create_user(
                    email=email,
                    password=password,
                    handle=handle,
                    display_name=display_name.strip(),
                    status=UserStatus.PENDING if mode == RegistrationMode.VERIFY_FIRST else UserStatus.ACTIVE,
                )
                ensure_user_settings(user)
                for purpose, granted in (consents or {}).items():
                    record_consent(user, purpose=purpose, granted=granted, version=consent_version, meta=meta)
                audit(AuditAction.ACCOUNT_REGISTERED, actor=user, target=user, metadata={"mode": mode})
                publish(events.USER_CREATED, {"user_id": user.pk}, actor=user)
                send_verification_email(user)
        except IntegrityError:
            # Lost a race on email or handle.
            if handle and User.all_objects.filter(handle=handle).exists():
                raise ValidationError(details={"handle": ["This handle is not available."]}) from None
            duplicate = True
        else:
            return RegistrationResult(user=user, created=True, mode=mode)

    # Hash anyway so response timing matches the account-creation path.
    User().set_password(password)
    if mode == RegistrationMode.VERIFY_FIRST:
        _notify_existing_account(email)
        return RegistrationResult(user=None, created=False, mode=mode)
    raise ValidationError(
        details={"email": ["Unable to register with this email address."]}, code="registration_failed"
    )


@transaction.atomic
def create_user_from_external_identity(*, email: str, email_verified: bool, display_name: str = "") -> Any:
    """Create an account for a first-time external (OAuth/OIDC) sign-in."""
    user = get_user_model().objects.create_user(
        email=normalize_email(email),
        password=None,
        display_name=display_name.strip()[:100],
        status=UserStatus.ACTIVE,
        email_verified_at=timezone.now() if email_verified else None,
    )
    ensure_user_settings(user)
    audit(AuditAction.ACCOUNT_REGISTERED, actor=user, target=user, metadata={"mode": "external"})
    publish(events.USER_CREATED, {"user_id": user.pk}, actor=user)
    if not email_verified:
        send_verification_email(user)
    return user
