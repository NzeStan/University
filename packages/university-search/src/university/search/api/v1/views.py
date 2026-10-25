from __future__ import annotations

from rest_framework import permissions, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.schema import OpenApiParameter, extend_schema
from university.core.context import get_request_context
from university.search import services
from university.search.conf import search_settings


class SearchResultSerializer(serializers.Serializer):
    content_type = serializers.CharField()
    object_id = serializers.CharField()
    title = serializers.CharField()
    snippet = serializers.CharField()
    score = serializers.FloatField()


class SearchPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()


def _fingerprint() -> str:
    ctx = get_request_context()
    return f"{ctx.ip_address or ''}|{ctx.user_agent[:200]}"


class SearchView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[
            OpenApiParameter("q", str, required=True),
            OpenApiParameter("types", str),
            OpenApiParameter("limit", int),
        ],
        responses=SearchResultSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        params = request.query_params
        try:
            limit = int(params.get("limit", 20))
        except ValueError:
            limit = 20
        types = [t for t in (params.get("types") or "").split(",") if t]
        results = services.search(
            viewer=request.user, q=params.get("q", ""), types=types, limit=limit, fingerprint=_fingerprint()
        )
        return Response(results)


class PeopleSearchView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(parameters=[OpenApiParameter("q", str, required=True)], responses=SearchPersonSerializer(many=True))
    def get(self, request: Request) -> Response:
        return Response(
            services.people(viewer=request.user, q=request.query_params.get("q", ""), fingerprint=_fingerprint())
        )


class SearchTypesView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=serializers.ListSerializer(child=serializers.CharField()))
    def get(self, request: Request) -> Response:
        from university.core.registry import registry

        sources = search_settings.get("SOURCES") or {}
        return Response(sorted(t for t in sources if t in registry.content_adapters))
