"""OpenAPI helpers that work with or without drf-spectacular.

Modules import schema decorators from here so drf-spectacular remains an
optional dependency (``pip install 'university-core[openapi]'``)::

    from university.core.api.schema import extend_schema, OpenApiParameter
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

try:
    from drf_spectacular.types import OpenApiTypes
    from drf_spectacular.utils import (
        OpenApiExample,
        OpenApiParameter,
        OpenApiResponse,
        extend_schema,
        extend_schema_field,
        extend_schema_view,
        inline_serializer,
    )

    SPECTACULAR_INSTALLED = True
except ImportError:  # pragma: no cover - exercised only without the extra
    SPECTACULAR_INSTALLED = False

    def _passthrough(*args: Any, **kwargs: Any) -> Callable[[Any], Any]:
        def decorator(obj: Any) -> Any:
            return obj

        return decorator

    extend_schema = _passthrough  # type: ignore[assignment]
    extend_schema_view = _passthrough  # type: ignore[assignment]
    extend_schema_field = _passthrough  # type: ignore[assignment]

    class _Stub:
        def __init__(self, *args: Any, **kwargs: Any) -> None:
            self.args, self.kwargs = args, kwargs

    class OpenApiTypes:  # type: ignore[no-redef]
        OBJECT = dict
        BINARY = bytes
        STR = str

    OpenApiParameter = _Stub  # type: ignore[assignment,misc]
    OpenApiExample = _Stub  # type: ignore[assignment,misc]
    OpenApiResponse = _Stub  # type: ignore[assignment,misc]

    def inline_serializer(*args: Any, **kwargs: Any) -> Any:  # type: ignore[misc]
        return None


ERROR_RESPONSE_SCHEMA = {
    "type": "object",
    "properties": {
        "error": {
            "type": "object",
            "properties": {
                "code": {"type": "string", "example": "permission_denied"},
                "message": {"type": "string"},
                "details": {"type": "object"},
                "request_id": {"type": "string", "nullable": True},
            },
            "required": ["code", "message", "details"],
        }
    },
}


def spectacular_settings(**overrides: Any) -> dict[str, Any]:
    """Recommended ``SPECTACULAR_SETTINGS`` for a University deployment."""
    base: dict[str, Any] = {
        "TITLE": "University API",
        "DESCRIPTION": "Modular African campus platform API.",
        "VERSION": "1.0.0",
        "SERVE_INCLUDE_SCHEMA": False,
        "SCHEMA_PATH_PREFIX": r"/api/v[0-9]+",
        "COMPONENT_SPLIT_REQUEST": True,
        "SERVE_PERMISSIONS": ["rest_framework.permissions.AllowAny"],
        "APPEND_COMPONENTS": {"schemas": {"Error": ERROR_RESPONSE_SCHEMA}},
        "ENUM_NAME_OVERRIDES": {
            "UserStatusEnum": "university.users.constants.UserStatus",
            "ProfileVisibilityEnum": "university.users.constants.ProfileVisibility",
            "AuditOutcomeEnum": "university.audit.models.AuditOutcomeChoices",
        },
    }
    base.update(overrides)
    return base


__all__ = [
    "ERROR_RESPONSE_SCHEMA",
    "SPECTACULAR_INSTALLED",
    "OpenApiExample",
    "OpenApiParameter",
    "OpenApiResponse",
    "OpenApiTypes",
    "extend_schema",
    "extend_schema_field",
    "extend_schema_view",
    "inline_serializer",
    "spectacular_settings",
]
