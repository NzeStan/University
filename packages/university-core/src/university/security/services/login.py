"""Credential login, multi-factor completion and passwordless login."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any

from django.contrib.auth import get_user_model

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.crypto import keyed_hash
from university.core.events import publish
from university.core.exceptions import AuthenticationFailed, NotFound, PermissionDenied, RateLimited
from university.core.http import ClientMeta, storable_ip
from university.security import events
from university.security.models import LoginAttempt, OTPChallenge, UserSession
from university.security.services import lockout
from university.security.services.otp import issue_otp, verify_otp
from university.security.services.sessions import create_session
from university.security.tokens import TokenPair
from university.users.backends import find_user_by_identifier, lift_expired_suspension
from university.users.constants import UserStatus

MFA_PURPOSE = "login_mfa"
PASSWORDLESS_PURPOSE = "login_passwordless"

_GENERIC = "Invalid credentials."


@dataclass(frozen=True)
class LoginResult:
    tokens: TokenPair | None = None
    session: UserSession | None = None
    user: Any = None
    mfa_required: bool = False
    challenge: OTPChallenge | None = None


def identifier_hash(identifier: str) -> str:
    return keyed_hash((identifier or "").strip().lower(), purpose="login-identifier")


def _record_attempt(ident_hash: str, meta: ClientMeta, *, user: Any, success: bool, reason: str = "") -> None:
    LoginAttempt.objects.create(
        identifier_hash=ident_hash,
        user=user,
        ip_address=storable_ip(meta.ip_address),
        user_agent=meta.user_agent,
        successful=success,
        failure_reason=reason[:64],
    )


def _fail(ident_hash: str, meta: ClientMeta, *, user: Any, reason: str) -> None:
    _record_attempt(ident_hash, meta, user=user, success=False, reason=reason)
    audit(
        AuditAction.LOGIN_FAILED,
        actor=None,
        outcome="failure",
        target_type="university_users.user" if user is not None else "",
        target_id=user.pk if user is not None else None,
        metadata={"reason": reason, "identifier_hash": ident_hash[:16]},
        ip_address=meta.ip_address,
        user_agent=meta.user_agent,
    )
    if lockout.register_failure(ident_hash, meta.ip_address):
        audit(AuditAction.LOGIN_LOCKED, outcome="denied", metadata={"identifier_hash": ident_hash[:16]})
        publish(events.LOGIN_LOCKED, {"identifier_hash": ident_hash[:16]})


def _check_status(user: Any, ident_hash: str, meta: ClientMeta) -> None:
    lift_expired_suspension(user)
    if user.status == UserStatus.ACTIVE:
        return
    if user.status == UserStatus.SUSPENDED:
        _record_attempt(ident_hash, meta, user=user, success=False, reason="suspended")
        raise PermissionDenied(
            "This account is suspended.",
            code="account_suspended",
            details={"until": user.suspended_until.isoformat() if user.suspended_until else None},
        )
    if user.status == UserStatus.BANNED:
        _record_attempt(ident_hash, meta, user=user, success=False, reason="banned")
        raise PermissionDenied("This account has been banned.", code="account_banned")
    if user.status == UserStatus.PENDING and university_settings.get("AUTH.REVEAL_UNVERIFIED_ACCOUNT_ON_LOGIN", False):
        _record_attempt(ident_hash, meta, user=user, success=False, reason="unverified")
        raise AuthenticationFailed("Verify your email address to sign in.", code="email_not_verified")
    _fail(ident_hash, meta, user=user, reason=f"status_{user.status}")
    raise AuthenticationFailed(_GENERIC, code="invalid_credentials")


def _mfa_destination(user: Any) -> tuple[str, str] | None:
    from university.users.services.preferences import get_security_settings

    if not university_settings.get("AUTH.MFA.ENABLED", True):
        return None
    sec = get_security_settings(user)
    if not sec.mfa_enabled:
        return None
    if sec.mfa_channel == "sms" and user.phone_verified_at and user.phone_number:
        return "sms", user.phone_number
    return "email", user.email


def login_with_password(*, identifier: str, password: str, meta: ClientMeta) -> LoginResult:
    ident_hash = identifier_hash(identifier)
    retry_after = lockout.check_lockout(ident_hash, meta.ip_address)
    if retry_after:
        raise RateLimited(
            "Too many failed sign-in attempts. Try again later.", code="login_locked", retry_after=retry_after
        )

    user = find_user_by_identifier(identifier)
    if user is None:
        get_user_model()().set_password(password)  # equalise timing
        _fail(ident_hash, meta, user=None, reason="unknown_identifier")
        raise AuthenticationFailed(_GENERIC, code="invalid_credentials")
    if not user.check_password(password):
        _fail(ident_hash, meta, user=user, reason="bad_password")
        raise AuthenticationFailed(_GENERIC, code="invalid_credentials")

    _check_status(user, ident_hash, meta)
    lockout.clear_failures(ident_hash, meta.ip_address)
    _record_attempt(ident_hash, meta, user=user, success=True)

    mfa = _mfa_destination(user)
    if mfa is not None:
        channel, destination = mfa
        challenge = issue_otp(purpose=MFA_PURPOSE, channel=channel, destination=destination, user=user)
        audit(AuditAction.LOGIN_MFA_CHALLENGED, actor=user, target=challenge, metadata={"channel": channel})
        return LoginResult(user=user, mfa_required=True, challenge=challenge)

    session, tokens = create_session(user, meta=meta, auth_method="password")
    return LoginResult(tokens=tokens, session=session, user=user)


def complete_mfa_login(*, challenge_id: Any, code: str, meta: ClientMeta) -> LoginResult:
    challenge = verify_otp(challenge_id=challenge_id, code=code, purpose=MFA_PURPOSE)
    user = challenge.user
    if user is None or user.status != UserStatus.ACTIVE:
        raise AuthenticationFailed(_GENERIC, code="invalid_credentials")
    session, tokens = create_session(user, meta=meta, auth_method="password+otp")
    return LoginResult(tokens=tokens, session=session, user=user)


@dataclass(frozen=True)
class PasswordlessChallenge:
    challenge_id: Any
    channel: str


def request_passwordless_code(*, identifier: str, meta: ClientMeta) -> PasswordlessChallenge:
    """Send a sign-in code. Returns a challenge id even for unknown accounts."""
    if not university_settings.get("AUTH.PASSWORDLESS.ENABLED", False):
        raise NotFound()
    ident_hash = identifier_hash(identifier)
    retry_after = lockout.check_lockout(ident_hash, meta.ip_address)
    if retry_after:
        raise RateLimited(retry_after=retry_after)
    user = find_user_by_identifier(identifier)
    channel = "sms" if identifier.strip().startswith("+") else "email"
    if user is None or user.status != UserStatus.ACTIVE:
        return PasswordlessChallenge(challenge_id=uuid.uuid4(), channel=channel)
    destination = user.phone_number if channel == "sms" else user.email
    challenge = issue_otp(purpose=PASSWORDLESS_PURPOSE, channel=channel, destination=destination, user=user)
    return PasswordlessChallenge(challenge_id=challenge.pk, channel=channel)


def complete_passwordless_login(*, challenge_id: Any, code: str, meta: ClientMeta) -> LoginResult:
    if not university_settings.get("AUTH.PASSWORDLESS.ENABLED", False):
        raise NotFound()
    challenge = verify_otp(challenge_id=challenge_id, code=code, purpose=PASSWORDLESS_PURPOSE)
    user = challenge.user
    if user is None or user.status != UserStatus.ACTIVE:
        raise AuthenticationFailed(_GENERIC, code="invalid_credentials")
    session, tokens = create_session(user, meta=meta, auth_method="passwordless")
    return LoginResult(tokens=tokens, session=session, user=user)
