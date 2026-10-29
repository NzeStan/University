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
    "paginated",
    "spectacular_settings",
]


_PAGINATED: dict[tuple[str, str], Any] = {}


def paginated(item: Any, *, style: str = "page") -> Any:
    """Response schema for a list that a view paginates itself.

    Views that call a paginator by hand must say so, or the published schema describes a bare
    array while clients receive a page object::

        @extend_schema(responses=paginated(CommunitySerializer))            # count/next/previous/results
        @extend_schema(responses=paginated(PostSchema, style="cursor"))     # next/previous/results
        @extend_schema(responses=paginated(PostSchema, style="offset"))     # offset/limit/results

    ``item`` is a serializer class or instance. The component is named ``Paginated<Item>List``,
    ``Cursor<Item>List`` or ``Offset<Item>List``.
    """
    from rest_framework import serializers

    if style not in ("page", "cursor", "offset"):
        raise ValueError(f"Unknown pagination style {style!r}")
    if isinstance(item, serializers.BaseSerializer):
        item = getattr(item, "child", item).__class__
    base = item.__name__.removesuffix("Serializer")
    key = (f"{item.__module__}.{item.__qualname__}", style)
    if key in _PAGINATED:
        return _PAGINATED[key]
    if style == "page":
        fields: dict[str, Any] = {
            "count": serializers.IntegerField(),
            "next": serializers.URLField(allow_null=True),
            "previous": serializers.URLField(allow_null=True),
        }
        name = f"Paginated{base}ListSerializer"
    elif style == "cursor":
        fields = {"next": serializers.URLField(allow_null=True), "previous": serializers.URLField(allow_null=True)}
        name = f"Cursor{base}ListSerializer"
    else:
        fields = {"offset": serializers.IntegerField(), "limit": serializers.IntegerField()}
        name = f"Offset{base}ListSerializer"
    fields["results"] = item(many=True)
    attrs = {**fields, "__module__": item.__module__, "_university_paginated": True}
    _PAGINATED[key] = type(name, (serializers.Serializer,), attrs)
    return _PAGINATED[key]


def _is_paginated(serializer: Any) -> bool:
    if isinstance(serializer, dict) and serializer:
        serializer = {str(code): value for code, value in serializer.items()}
        serializer = serializer[min(serializer)]
    cls = serializer if isinstance(serializer, type) else type(serializer)
    return bool(getattr(cls, "_university_paginated", False))
