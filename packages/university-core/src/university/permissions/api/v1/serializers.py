from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.serializers import StrictModelSerializer
from university.core.registry import registry
from university.permissions.models import Role, RoleAssignment


class PermissionSerializer(serializers.Serializer):
    code = serializers.CharField()
    description = serializers.CharField()
    scopes = serializers.ListField(child=serializers.CharField())
    sensitive = serializers.BooleanField()


class RoleSerializer(StrictModelSerializer):
    class Meta:
        model = Role
        fields = ("id", "key", "name", "description", "scope_type", "permissions", "is_system", "created_at")
        read_only_fields = ("id", "is_system", "created_at")

    def validate_scope_type(self, value: str) -> str:
        if value not in registry.scope_types:
            raise serializers.ValidationError("Unknown scope type.")
        return value

    def validate_permissions(self, value: Any) -> list[str]:
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise serializers.ValidationError("Must be a list of permission codes.")
        unknown = [code for code in value if code != "*" and not registry.permission_exists(code)]
        if unknown:
            raise serializers.ValidationError(f"Unknown permissions: {', '.join(unknown)}")
        return sorted(set(value))


class RoleAssignmentSerializer(StrictModelSerializer):
    role = serializers.SlugRelatedField(slug_field="key", read_only=True)
    user = serializers.UUIDField(source="user_id", read_only=True)

    class Meta:
        model = RoleAssignment
        fields = ("id", "user", "role", "scope_type", "scope_id", "expires_at", "revoked_at", "created_at")
        read_only_fields = fields


class RoleAssignmentCreateSerializer(serializers.Serializer):
    user = serializers.UUIDField()
    role = serializers.SlugField()
    scope_type = serializers.CharField(default="platform")
    scope_id = serializers.CharField(required=False, allow_blank=True, default="")
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class EffectivePermissionsSerializer(serializers.Serializer):
    scope_type = serializers.CharField()
    scope_id = serializers.CharField(allow_blank=True)
    permissions = serializers.ListField(child=serializers.CharField())
