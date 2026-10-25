from __future__ import annotations

from typing import Any

from rest_framework import generics, permissions

from university.audit.api.v1.serializers import ActivitySerializer, AuditLogSerializer
from university.audit.selectors import activity_for_user, filter_audit_log
from university.core.api.pagination import CursorPagination
from university.core.api.schema import OpenApiParameter, extend_schema
from university.permissions.drf import require_permission


class AuditLogListView(generics.ListAPIView):
    """Platform audit log (requires ``audit.view``)."""

    serializer_class = AuditLogSerializer
    permission_classes = [permissions.IsAuthenticated, require_permission("audit.view")]

    @extend_schema(
        parameters=[
            OpenApiParameter(name, str, required=False)
            for name in ("action", "category", "outcome", "actor", "target_type", "target_id", "since", "until")
        ]
    )
    def get(self, request: Any, *args: Any, **kwargs: Any) -> Any:
        return super().get(request, *args, **kwargs)

    def get_queryset(self) -> Any:
        return filter_audit_log(self.request.query_params)


class MyActivityView(generics.ListAPIView):
    """The authenticated user's own security activity."""

    serializer_class = ActivitySerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CursorPagination

    def get_queryset(self) -> Any:
        return activity_for_user(self.request.user)
