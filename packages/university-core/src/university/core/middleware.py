"""University middleware.

``RequestContextMiddleware`` (required) assigns every request a correlation
id, captures client metadata into :mod:`university.core.context` and echoes
``X-Request-ID`` on the response.

``APISecurityHeadersMiddleware`` (recommended) hardens JSON API responses:
``Cache-Control: no-store`` for authenticated traffic, a locked-down
Content-Security-Policy and ``X-Content-Type-Options: nosniff``. Django's own
``SecurityMiddleware`` remains responsible for HSTS, SSL redirects, etc.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable

from django.http import HttpRequest, HttpResponse

from university.core.conf import university_settings
from university.core.context import RequestContext, reset_request_context, set_request_context
from university.core.http import get_client_ip, get_user_agent

REQUEST_ID_HEADER = "X-Request-ID"
_REQUEST_ID_RE = re.compile(r"^[A-Za-z0-9._\-]{8,128}$")


class RequestContextMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def _request_id(self, request: HttpRequest) -> str:
        if university_settings.get("SECURITY.TRUST_INCOMING_REQUEST_ID", False):
            incoming = request.headers.get(REQUEST_ID_HEADER, "")
            if _REQUEST_ID_RE.match(incoming):
                return incoming
        return uuid.uuid4().hex

    def __call__(self, request: HttpRequest) -> HttpResponse:
        request_id = self._request_id(request)
        request.request_id = request_id  # type: ignore[attr-defined]
        token = set_request_context(
            RequestContext(
                request_id=request_id,
                ip_address=get_client_ip(request),
                user_agent=get_user_agent(request),
                method=request.method or "",
                path=request.path[:512],
            )
        )
        try:
            response = self.get_response(request)
        finally:
            reset_request_context(token)
        response[REQUEST_ID_HEADER] = request_id
        return response


class APISecurityHeadersMiddleware:
    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        response = self.get_response(request)
        prefix = "/" + str(university_settings.get("API.URL_PREFIX", "api")).strip("/") + "/"
        if not request.path.startswith(prefix):
            return response
        response.setdefault("X-Content-Type-Options", "nosniff")
        csp = university_settings.get("SECURITY.API_CONTENT_SECURITY_POLICY")
        if csp and "Content-Security-Policy" not in response:
            response["Content-Security-Policy"] = csp
        has_credentials = (
            "HTTP_AUTHORIZATION" in request.META
            or "HTTP_COOKIE" in request.META
            or bool(getattr(getattr(request, "user", None), "is_authenticated", False))
        )
        cache_control = university_settings.get("SECURITY.API_CACHE_CONTROL")
        if has_credentials and cache_control and "Cache-Control" not in response:
            response["Cache-Control"] = cache_control
            response.setdefault("Vary", "Authorization, Cookie")
        return response
