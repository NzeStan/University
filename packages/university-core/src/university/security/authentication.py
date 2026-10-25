"""DRF authentication classes.

Configure in ``REST_FRAMEWORK["DEFAULT_AUTHENTICATION_CLASSES"]`` (see
:func:`university.core.settings.rest_framework_settings`). Any class can be
removed or replaced; nothing else in University assumes JWT.

* :class:`JWTAuthentication` — ``Authorization: Bearer <access token>``.
* :class:`APIKeyAuthentication` — ``Authorization: Api-Key <key>`` or the
  configured header (``X-API-Key``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone
from rest_framework import exceptions
from rest_framework.authentication import BaseAuthentication, get_authorization_header

from university.core.conf import university_settings
from university.core.crypto import constant_time_equals
from university.core.http import get_client_ip, storable_ip
from university.security.context import AuthContext
from university.security.models import UserSession
from university.security.tokens import get_token_issuer, stamp_fingerprint
from university.users.constants import UserStatus

_INVALID = "Invalid or expired credentials."


class JWTAuthentication(BaseAuthentication):
    keyword = b"bearer"

    def authenticate(self, request: Any) -> tuple[Any, AuthContext] | None:
        parts = get_authorization_header(request).split()
        if not parts or parts[0].lower() != self.keyword:
            return None
        if len(parts) != 2:
            raise exceptions.AuthenticationFailed("Invalid authorization header.", code="invalid_header")
        try:
            token = parts[1].decode("ascii")
        except UnicodeError:
            raise exceptions.AuthenticationFailed("Invalid authorization header.", code="invalid_header") from None

        claims = get_token_issuer().decode_access(token)
        session = (
            UserSession.objects.select_related("user").filter(pk=claims.session_id, user_id=claims.user_id).first()
        )
        if session is None:
            raise exceptions.AuthenticationFailed(_INVALID, code="token_invalid")
        user = session.user
        now = timezone.now()
        if (
            session.revoked_at is not None
            or session.expires_at <= now
            or user.status != UserStatus.ACTIVE
            or session.security_stamp != user.security_stamp
            or not constant_time_equals(claims.stamp, stamp_fingerprint(user.security_stamp))
        ):
            raise exceptions.AuthenticationFailed(_INVALID, code="token_invalid")
        self._touch(request, session, now)
        return user, AuthContext(method="jwt", session=session, claims=claims)

    @staticmethod
    def _touch(request: Any, session: UserSession, now: dt.datetime) -> None:
        interval = int(university_settings.get("AUTH.SESSION_TOUCH_INTERVAL_SECONDS", 300))
        threshold = now - dt.timedelta(seconds=interval)
        if session.last_seen_at < threshold:
            UserSession.objects.filter(pk=session.pk, last_seen_at__lt=threshold).update(
                last_seen_at=now, last_ip_address=storable_ip(get_client_ip(request))
            )

    def authenticate_header(self, request: Any) -> str:
        return 'Bearer realm="api"'


class APIKeyAuthentication(BaseAuthentication):
    keyword = b"api-key"

    def _extract(self, request: Any) -> str | None:
        parts = get_authorization_header(request).split()
        if parts and parts[0].lower() == self.keyword:
            if len(parts) != 2:
                raise exceptions.AuthenticationFailed("Invalid authorization header.", code="invalid_header")
            return parts[1].decode("ascii", "ignore")
        header = university_settings.get("AUTH.API_KEYS.HEADER", "X-API-Key")
        value = request.headers.get(header) if header else None
        return value.strip() if value else None

    def authenticate(self, request: Any) -> tuple[Any, AuthContext] | None:
        if not university_settings.get("AUTH.API_KEYS.ENABLED", True):
            return None
        raw = self._extract(request)
        if not raw:
            return None
        from university.security.services.api_keys import authenticate_api_key

        api_key = authenticate_api_key(raw, ip_address=get_client_ip(request))
        if api_key is None:
            raise exceptions.AuthenticationFailed(_INVALID, code="api_key_invalid")
        return api_key.user, AuthContext(method="api_key", api_key=api_key)

    def authenticate_header(self, request: Any) -> str:
        return 'Api-Key realm="api"'
