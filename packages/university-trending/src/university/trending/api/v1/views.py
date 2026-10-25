from __future__ import annotations

from rest_framework import permissions, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.schema import OpenApiParameter, extend_schema
from university.trending import services


class TrendingItemSerializer(serializers.Serializer):
    content_type = serializers.CharField()
    object_id = serializers.CharField()
    score = serializers.FloatField()
    title = serializers.CharField()


class TrendingView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in ("type", "scope_type", "scope_id")]
        + [OpenApiParameter("limit", int)],
        responses=TrendingItemSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        params = request.query_params
        scope = (
            (params["scope_type"], params["scope_id"]) if params.get("scope_type") and params.get("scope_id") else None
        )
        try:
            limit = max(1, min(int(params.get("limit", 20)), 50))
        except ValueError:
            limit = 20
        items = services.trending(
            viewer=request.user, content_type=params.get("type") or None, scope=scope, limit=limit
        )
        return Response(items)
