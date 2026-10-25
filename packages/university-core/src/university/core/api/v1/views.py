from __future__ import annotations

from typing import Any

from rest_framework import permissions, serializers
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.schema import extend_schema
from university.core.registry import registry


class ModuleSerializer(serializers.Serializer):
    name = serializers.CharField()
    version = serializers.CharField(required=False)


class ModulesView(APIView):
    """Installed University modules, so clients can adapt to capabilities.

    Versions are only disclosed to staff (avoids fingerprinting).
    """

    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=ModuleSerializer(many=True))
    def get(self, request: Request, *args: Any, **kwargs: Any) -> Response:
        is_staff = bool(getattr(request.user, "is_staff", False))
        data = [
            {"name": m.name, **({"version": m.version} if is_staff else {})}
            for m in sorted(registry.all(), key=lambda m: m.name)
        ]
        return Response(data)
