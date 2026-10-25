"""Consistent API error responses.

Every error leaves the API in one envelope::

    {
        "error": {
            "code": "permission_denied",
            "message": "You do not have permission to perform this action.",
            "details": {},
            "request_id": "8c1f…"
        }
    }

Stack traces, SQL, file paths and exception messages from unexpected errors
are never returned; they are logged with the request id instead.
"""

from __future__ import annotations

import logging
from typing import Any

from django.conf import settings
from django.core.exceptions import PermissionDenied as DjangoPermissionDenied
from django.core.exceptions import ValidationError as DjangoValidationError
from django.http import Http404
from rest_framework import exceptions as drf_exceptions
from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import exception_handler as drf_exception_handler

from university.core.context import get_request_context
from university.core.exceptions import UniversityError

logger = logging.getLogger("university.api")

_CODE_OVERRIDES = {
    drf_exceptions.NotAuthenticated: "not_authenticated",
    drf_exceptions.AuthenticationFailed: "authentication_failed",
    drf_exceptions.PermissionDenied: "permission_denied",
    drf_exceptions.NotFound: "not_found",
    drf_exceptions.MethodNotAllowed: "method_not_allowed",
    drf_exceptions.NotAcceptable: "not_acceptable",
    drf_exceptions.UnsupportedMediaType: "unsupported_media_type",
    drf_exceptions.Throttled: "rate_limited",
    drf_exceptions.ParseError: "parse_error",
    drf_exceptions.ValidationError: "invalid",
}


def error_body(code: str, message: str, details: Any = None) -> dict[str, Any]:
    return {
        "error": {
            "code": code,
            "message": message,
            "details": details if details is not None else {},
            "request_id": get_request_context().request_id,
        }
    }


def _code_for(exc: drf_exceptions.APIException) -> str:
    for cls in type(exc).__mro__:
        if cls in _CODE_OVERRIDES:
            return _CODE_OVERRIDES[cls]
    codes = exc.get_codes()
    return codes if isinstance(codes, str) else "error"


def exception_handler(exc: Exception, context: dict[str, Any]) -> Response | None:
    if isinstance(exc, UniversityError):
        response = Response(error_body(exc.code, exc.message, exc.details), status=exc.status_code)
        retry_after = getattr(exc, "retry_after", None)
        if retry_after:
            response["Retry-After"] = str(int(retry_after))
        return response

    if isinstance(exc, DjangoValidationError):
        detail = exc.message_dict if hasattr(exc, "error_dict") else {"non_field_errors": exc.messages}
        exc = drf_exceptions.ValidationError(detail=detail)
    elif isinstance(exc, Http404):
        exc = drf_exceptions.NotFound()
    elif isinstance(exc, DjangoPermissionDenied):
        exc = drf_exceptions.PermissionDenied()

    response = drf_exception_handler(exc, context)
    if response is None:
        logger.exception("Unhandled API error", exc_info=exc)
        if settings.DEBUG:
            return None  # Let Django render the debug page during development.
        return Response(
            error_body("server_error", "An unexpected error occurred."),
            status=status.HTTP_500_INTERNAL_SERVER_ERROR,
        )

    if not isinstance(exc, drf_exceptions.APIException):  # pragma: no cover - DRF contract
        return response
    code = _code_for(exc)
    if isinstance(exc, drf_exceptions.ValidationError):
        message, details = "Invalid input.", response.data
    elif isinstance(exc, drf_exceptions.Throttled):
        message = "Too many requests. Please try again later."
        details = {"retry_after": int(exc.wait)} if exc.wait is not None else {}
    else:
        detail = response.data.get("detail", "") if isinstance(response.data, dict) else ""
        message, details = str(detail) or "Request failed.", {}
    response.data = error_body(code, message, details)
    return response
