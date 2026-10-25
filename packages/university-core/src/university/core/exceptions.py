"""Domain exceptions raised by University services.

Services raise these instead of HTTP-specific errors; the API exception
handler (:mod:`university.core.api.exceptions`) renders them in the standard
error envelope::

    {"error": {"code": "permission_denied", "message": "...", "details": {}}}
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured


class UniversityError(Exception):
    """Base class for expected, user-facing service errors."""

    status_code: int = 400
    default_code: str = "error"
    default_message: str = "The request could not be processed."

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> None:
        self.message = message or self.default_message
        self.code = code or self.default_code
        self.details = details or {}
        super().__init__(self.message)


class ValidationError(UniversityError):
    status_code = 400
    default_code = "invalid"
    default_message = "Invalid input."


class AuthenticationFailed(UniversityError):
    status_code = 401
    default_code = "authentication_failed"
    default_message = "Authentication failed."


class PermissionDenied(UniversityError):
    status_code = 403
    default_code = "permission_denied"
    default_message = "You do not have permission to perform this action."


class NotFound(UniversityError):
    status_code = 404
    default_code = "not_found"
    default_message = "Not found."


class Conflict(UniversityError):
    status_code = 409
    default_code = "conflict"
    default_message = "The request conflicts with the current state."


class Gone(UniversityError):
    status_code = 410
    default_code = "gone"
    default_message = "This resource is no longer available."


class RateLimited(UniversityError):
    status_code = 429
    default_code = "rate_limited"
    default_message = "Too many requests. Please try again later."

    def __init__(self, message: str | None = None, *, retry_after: int | None = None, **kwargs: Any) -> None:
        details = kwargs.pop("details", None) or {}
        if retry_after is not None:
            details["retry_after"] = int(retry_after)
        super().__init__(message, details=details, **kwargs)
        self.retry_after = retry_after


class ServiceUnavailable(UniversityError):
    status_code = 503
    default_code = "service_unavailable"
    default_message = "The service is temporarily unavailable."


class ModuleNotInstalled(ImproperlyConfigured):
    """Raised when code requires an optional University module that is absent."""

    def __init__(self, name: str) -> None:
        self.module_name = name
        super().__init__(
            f"The University module {name!r} is not installed. "
            f"Install the 'university-{name}' package and add it to INSTALLED_APPS."
        )


class ProviderError(UniversityError):
    """An external provider (email, SMS, payments …) failed."""

    status_code = 502
    default_code = "provider_error"
    default_message = "An upstream provider failed. Please try again later."
