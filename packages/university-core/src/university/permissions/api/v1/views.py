from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from django.shortcuts import get_object_or_404
from rest_framework import generics, permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.api.schema import extend_schema
from university.core.exceptions import NotFound, PermissionDenied
from university.core.registry import registry
from university.permissions.api.v1 import serializers as s
from university.permissions.drf import require_permission
from university.permissions.models import Role, RoleAssignment
from university.permissions.scopes import Scope
from university.permissions.services import (
    assign_role,
    authorize,
    get_effective_permissions,
    revoke_role,
)


def _scope_from(params: Any) -> Scope:
    scope_type = params.get("scope_type") or "platform"
    return Scope(scope_type, params.get("scope_id") or "")


class PermissionListView(APIView):
    permission_classes = [permissions.IsAuthenticated, require_permission("permissions.roles.view")]

    @extend_schema(responses=s.PermissionSerializer(many=True))
    def get(self, request: Request) -> Response:
        data = [
            {"code": p.code, "description": p.description, "scopes": list(p.scopes), "sensitive": p.sensitive}
            for p in sorted(registry.permissions.values(), key=lambda p: p.code)
        ]
        return Response(data)


class RoleListCreateView(generics.ListCreateAPIView):
    serializer_class = s.RoleSerializer
    queryset = Role.objects.all()

    def get_permissions(self) -> list[Any]:
        code = "permissions.roles.manage" if self.request.method == "POST" else "permissions.roles.view"
        return [permissions.IsAuthenticated(), require_permission(code)()]

    def perform_create(self, serializer: Any) -> None:
        role = serializer.save(is_system=False)
        audit(AuditAction.ROLE_CREATED, actor=self.request.user, target=role, metadata={"key": role.key})


class RoleDetailView(generics.RetrieveUpdateAPIView):
    serializer_class = s.RoleSerializer
    queryset = Role.objects.all()
    lookup_field = "id"
    http_method_names = ["get", "patch", "head", "options"]

    def get_permissions(self) -> list[Any]:
        code = (
            "permissions.roles.view" if self.request.method in permissions.SAFE_METHODS else "permissions.roles.manage"
        )
        return [permissions.IsAuthenticated(), require_permission(code)()]

    def perform_update(self, serializer: Any) -> None:
        if serializer.instance.is_system:
            raise PermissionDenied("System roles cannot be modified.", code="system_role")
        role = serializer.save()
        audit(AuditAction.ROLE_UPDATED, actor=self.request.user, target=role, metadata={"key": role.key})


class RoleAssignmentListCreateView(APIView):
    """List or grant role assignments at a scope (scope-level authorization)."""

    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.RoleAssignmentSerializer(many=True))
    def get(self, request: Request) -> Response:
        scope = _scope_from(request.query_params)
        authorize(request.user, "permissions.roles.view", scope)
        qs = RoleAssignment.objects.active().select_related("role").filter(scope_type=scope.type, scope_id=scope.id)
        user_id = request.query_params.get("user")
        if user_id:
            qs = qs.filter(user_id=user_id)
        page = qs.order_by("-created_at")[:500]
        return Response(s.RoleAssignmentSerializer(page, many=True).data)

    @extend_schema(request=s.RoleAssignmentCreateSerializer, responses=s.RoleAssignmentSerializer)
    def post(self, request: Request) -> Response:
        serializer = s.RoleAssignmentCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        scope = Scope(data["scope_type"], data.get("scope_id") or "")
        authorize(request.user, "permissions.roles.assign", scope)
        user = get_user_model().objects.filter(pk=data["user"]).first()
        if user is None:
            raise NotFound("User not found.")
        assignment = assign_role(
            user=user,
            role_key=data["role"],
            scope=scope,
            granted_by=request.user,
            expires_at=data.get("expires_at"),
        )
        return Response(s.RoleAssignmentSerializer(assignment).data, status=status.HTTP_201_CREATED)


class RoleAssignmentDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, assignment_id: Any) -> Response:
        assignment = get_object_or_404(RoleAssignment.objects.select_related("role"), pk=assignment_id)
        scope = Scope(assignment.scope_type, assignment.scope_id)
        # Do not reveal assignments outside the caller's authority.
        authorize(request.user, "permissions.roles.view", scope)
        revoke_role(assignment, revoked_by=request.user)
        return Response(status=status.HTTP_204_NO_CONTENT)


class MyPermissionsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.EffectivePermissionsSerializer)
    def get(self, request: Request) -> Response:
        scope = _scope_from(request.query_params)
        return Response(
            {
                "scope_type": scope.type,
                "scope_id": scope.id,
                "permissions": get_effective_permissions(request.user, scope),
            }
        )
