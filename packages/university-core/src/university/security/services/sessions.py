"""Session lifecycle and refresh-token rotation.

Every successful sign-in creates a :class:`UserSession` with an opaque refresh
token. Refreshing *rotates* the token: the old one is marked used and a new
one issued. Presenting an already-used refresh token means it was copied —
by an attacker or a buggy client — so the whole session is revoked
(refresh-token reuse detection, RFC 6819 §5.2.2.3).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.crypto import generate_token, keyed_hash, keyed_hash_candidates
from university.core.events import publish
from university.core.exceptions import AuthenticationFailed, NotFound
from university.core.http import ClientMeta, storable_ip
from university.security import events
from university.security.detection import get_detector
from university.security.models import RefreshToken, UserSession
from university.security.tokens import TokenPair, get_token_issuer
from university.users.constants import UserStatus

REFRESH_PURPOSE = "refresh-token"
REFRESH_PREFIX = "rt_"


def _seconds(path: str) -> dt.timedelta:
    return dt.timedelta(seconds=int(university_settings.get(path)))


def _new_refresh_token(session: UserSession) -> tuple[str, RefreshToken]:
    raw = REFRESH_PREFIX + generate_token(48)
    expires = min(timezone.now() + _seconds("AUTH.REFRESH_TOKEN_LIFETIME_SECONDS"), session.expires_at)
    token = RefreshToken.objects.create(
        session=session, token_hash=keyed_hash(raw, purpose=REFRESH_PURPOSE), expires_at=expires
    )
    return raw, token


def _token_pair(user: Any, session: UserSession, raw_refresh: str, refresh: RefreshToken) -> TokenPair:
    access, access_expires = get_token_issuer().issue_access(user=user, session=session)
    return TokenPair(
        access=access,
        refresh=raw_refresh,
        access_expires_at=access_expires,
        refresh_expires_at=refresh.expires_at,
        session_id=session.pk,
    )


def _enforce_session_limit(user: Any) -> None:
    limit = int(university_settings.get("AUTH.MAX_SESSIONS_PER_USER", 25))
    active = list(UserSession.objects.active().filter(user=user).order_by("-created_at").values_list("pk", flat=True))
    stale = active[limit:]
    if stale:
        revoke_sessions_by_id(stale, reason="session_limit")


@transaction.atomic
def create_session(user: Any, *, meta: ClientMeta, auth_method: str) -> tuple[UserSession, TokenPair]:
    """Sign ``user`` in on a new session and issue tokens."""
    risk = get_detector().assess(user, meta)
    now = timezone.now()
    session = UserSession.objects.create(
        user=user,
        auth_method=auth_method[:64],
        device_id=meta.device_id,
        device_name=meta.device_name,
        user_agent=meta.user_agent,
        ip_address=storable_ip(meta.ip_address),
        last_ip_address=storable_ip(meta.ip_address),
        last_seen_at=now,
        expires_at=now + _seconds("AUTH.SESSION_MAX_AGE_SECONDS"),
        security_stamp=user.security_stamp,
        risk_reasons=list(risk.reasons),
    )
    raw, refresh = _new_refresh_token(session)
    _enforce_session_limit(user)
    type(user).objects.filter(pk=user.pk).update(last_login=now)
    audit(
        AuditAction.LOGIN_SUCCEEDED,
        actor=user,
        target=session,
        metadata={"auth_method": auth_method, "risk": list(risk.reasons)},
    )
    publish(
        events.USER_LOGGED_IN, {"user_id": user.pk, "session_id": session.pk, "auth_method": auth_method}, actor=user
    )
    if risk.is_suspicious:
        audit(AuditAction.SUSPICIOUS_LOGIN, actor=user, target=session, metadata={"reasons": list(risk.reasons)})
        publish(
            events.LOGIN_SUSPICIOUS,
            {"user_id": user.pk, "session_id": session.pk, "reasons": list(risk.reasons)},
            actor=user,
        )
    return session, _token_pair(user, session, raw, refresh)


def rotate_refresh_token(raw_token: str, *, meta: ClientMeta) -> TokenPair:
    """Exchange a refresh token for a new token pair."""
    invalid = AuthenticationFailed("Invalid or expired refresh token.", code="refresh_invalid")
    if not raw_token or not raw_token.startswith(REFRESH_PREFIX) or len(raw_token) > 256:
        raise invalid
    token = (
        RefreshToken.objects.select_related("session", "session__user")
        .filter(token_hash__in=keyed_hash_candidates(raw_token, purpose=REFRESH_PURPOSE))
        .first()
    )
    if token is None:
        raise invalid
    session, user = token.session, token.session.user
    now = timezone.now()

    if token.used_at is not None:
        _handle_reuse(session)
        raise invalid
    idle_limit = session.last_seen_at + _seconds("AUTH.SESSION_IDLE_TIMEOUT_SECONDS")
    if (
        token.revoked_at is not None
        or token.expires_at <= now
        or session.revoked_at is not None
        or session.expires_at <= now
        or idle_limit <= now
        or user.status != UserStatus.ACTIVE
        or session.security_stamp != user.security_stamp
    ):
        raise invalid

    with transaction.atomic():
        # Compare-and-set: exactly one concurrent refresh can win.
        claimed = RefreshToken.objects.filter(pk=token.pk, used_at__isnull=True).update(used_at=now)
        if claimed:
            raw, new_token = _new_refresh_token(session)
            UserSession.objects.filter(pk=session.pk).update(
                last_seen_at=now, last_ip_address=storable_ip(meta.ip_address)
            )
    if not claimed:
        _handle_reuse(session)
        raise invalid
    return _token_pair(user, session, raw, new_token)


def _handle_reuse(session: UserSession) -> None:
    revoked = _revoke(session, reason="refresh_token_reuse")
    if revoked:
        audit(
            AuditAction.REFRESH_TOKEN_REUSED,
            actor=session.user,
            target=session,
            outcome="denied",
            category="security",
        )
        publish(events.REFRESH_TOKEN_REUSED, {"user_id": session.user_id, "session_id": session.pk})


def _revoke(session: UserSession, *, reason: str) -> bool:
    now = timezone.now()
    with transaction.atomic():
        updated = UserSession.objects.filter(pk=session.pk, revoked_at__isnull=True).update(
            revoked_at=now, revoked_reason=reason[:64]
        )
        RefreshToken.objects.filter(session_id=session.pk, revoked_at__isnull=True).update(revoked_at=now)
    return bool(updated)


def revoke_sessions_by_id(session_ids: list[Any], *, reason: str) -> int:
    now = timezone.now()
    with transaction.atomic():
        count = UserSession.objects.filter(pk__in=session_ids, revoked_at__isnull=True).update(
            revoked_at=now, revoked_reason=reason[:64]
        )
        RefreshToken.objects.filter(session_id__in=session_ids, revoked_at__isnull=True).update(revoked_at=now)
    return count


def revoke_session(session: UserSession, *, actor: Any, reason: str = "revoked") -> None:
    if _revoke(session, reason=reason):
        audit(AuditAction.SESSION_REVOKED, actor=actor, target=session, metadata={"reason": reason})
        publish(
            events.SESSION_REVOKED,
            {"user_id": session.user_id, "session_id": session.pk, "reason": reason},
            actor=actor,
        )


def revoke_user_session(user: Any, session_id: Any, *, reason: str = "revoked_by_user") -> None:
    """Revoke one of ``user``'s own sessions (404 for anyone else's)."""
    session = UserSession.objects.filter(pk=session_id, user=user).first()
    if session is None:
        raise NotFound("Session not found.")
    revoke_session(session, actor=user, reason=reason)


def revoke_user_sessions(user: Any, *, actor: Any, reason: str, except_session_id: Any = None) -> int:
    qs = UserSession.objects.filter(user=user, revoked_at__isnull=True)
    if except_session_id is not None:
        qs = qs.exclude(pk=except_session_id)
    ids = list(qs.values_list("pk", flat=True))
    count = revoke_sessions_by_id(ids, reason=reason) if ids else 0
    if count:
        audit(AuditAction.SESSIONS_REVOKED, actor=actor, target=user, metadata={"reason": reason, "count": count})
    return count


def logout(session: UserSession, *, user: Any) -> None:
    if _revoke(session, reason="logout"):
        audit(AuditAction.LOGOUT, actor=user, target=session)
        publish(events.USER_LOGGED_OUT, {"user_id": user.pk, "session_id": session.pk}, actor=user)
