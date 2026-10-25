from __future__ import annotations

import datetime as dt

from rest_framework import permissions, serializers, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.analytics import services
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.core.context import get_request_context
from university.core.exceptions import ValidationError
from university.permissions.scopes import Scope
from university.permissions.services import authorize

REPORT_PARAMS = [OpenApiParameter("from", str), OpenApiParameter("to", str), OpenApiParameter("metrics", str)]


class AnalyticsViewSerializer(serializers.Serializer):
    content_type = serializers.CharField(max_length=64)
    object_id = serializers.CharField(max_length=64)


class AnalyticsViewResultSerializer(serializers.Serializer):
    counted = serializers.BooleanField()


def _dates(request: Request) -> tuple[dt.date | None, dt.date | None]:
    try:
        start = dt.date.fromisoformat(request.query_params["from"]) if request.query_params.get("from") else None
        end = dt.date.fromisoformat(request.query_params["to"]) if request.query_params.get("to") else None
    except ValueError:
        raise ValidationError(details={"from": ["Use YYYY-MM-DD."]}) from None
    return start, end


def _metrics(request: Request) -> list[str]:
    return [m.strip() for m in (request.query_params.get("metrics") or "").split(",") if m.strip()][:50]


class RecordViewView(APIView):
    """Report that the caller viewed a piece of content (counted once per window; nobody stored)."""

    permission_classes = [permissions.AllowAny]

    @extend_schema(request=AnalyticsViewSerializer, responses={202: AnalyticsViewResultSerializer})
    def post(self, request: Request) -> Response:
        serializer = AnalyticsViewSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ctx = get_request_context()
        counted = services.record_view(
            viewer=request.user,
            fingerprint=f"{ctx.ip_address or ''}|{ctx.user_agent[:200]}",
            **serializer.validated_data,
        )
        return Response({"counted": counted}, status=status.HTTP_202_ACCEPTED)


class OverviewView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=REPORT_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request) -> Response:
        authorize(request.user, "analytics.view", audit_denial=True)
        start, end = _dates(request)
        return Response(services.report(start=start, end=end, metrics=_metrics(request)))


class ScopeReportView(APIView):
    """Analytics for one scope (an institution, community …), e.g. for its leadership."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(parameters=REPORT_PARAMS, responses=OpenApiTypes.OBJECT)
    def get(self, request: Request, scope_type: str, scope_id: str) -> Response:
        authorize(request.user, "analytics.view", Scope(scope_type, scope_id), audit_denial=True)
        start, end = _dates(request)
        return Response(services.report(start=start, end=end, metrics=_metrics(request), scope=(scope_type, scope_id)))


class MetricListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=serializers.ListSerializer(child=serializers.CharField()))
    def get(self, request: Request) -> Response:
        authorize(request.user, "analytics.view")
        return Response(services.known_metrics())
