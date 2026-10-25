from __future__ import annotations

from typing import Any

from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.__module__ import selectors, services
from university.__module__.api.v1 import serializers as s
from university.core.api.pagination import CursorPagination
from university.core.api.schema import extend_schema


class ItemListCreateView(generics.ListAPIView):
    serializer_class = s.ItemSerializer
    permission_classes = [permissions.IsAuthenticated]
    pagination_class = CursorPagination

    @property
    def throttle_scope(self) -> str | None:  # type: ignore[override]
        return "__module___item_create" if self.request.method == "POST" else None

    def get_queryset(self) -> Any:
        return selectors.items_for(self.request.user)

    @extend_schema(request=s.ItemCreateSerializer, responses={201: s.ItemSerializer})
    def post(self, request: Request) -> Response:
        serializer = s.ItemCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        item = services.create_item(actor=request.user, **serializer.validated_data)
        return Response(s.ItemSerializer(item).data, status=status.HTTP_201_CREATED)


class ItemDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, item_id: Any) -> Response:
        services.delete_item(actor=request.user, item_id=item_id)
        return Response(status=status.HTTP_204_NO_CONTENT)
