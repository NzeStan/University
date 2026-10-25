from __future__ import annotations

from rest_framework import serializers

from university.audit.models import AuditLog
from university.core.api.serializers import StrictModelSerializer


class AuditLogSerializer(StrictModelSerializer):
    class Meta:
        model = AuditLog
        fields = (
            "id",
            "created_at",
            "action",
            "category",
            "outcome",
            "actor_ref",
            "target_type",
            "target_id",
            "scope_type",
            "scope_id",
            "ip_address",
            "user_agent",
            "request_id",
            "metadata",
            "entry_hash",
        )
        read_only_fields = fields


class ActivitySerializer(StrictModelSerializer):
    """A user's own activity — no internal metadata."""

    class Meta:
        model = AuditLog
        fields = ("id", "created_at", "action", "outcome", "ip_address", "user_agent")
        read_only_fields = fields


class AuditFilterSerializer(serializers.Serializer):
    action = serializers.CharField(required=False)
    category = serializers.CharField(required=False)
    outcome = serializers.CharField(required=False)
    actor = serializers.UUIDField(required=False)
    target_type = serializers.CharField(required=False)
    target_id = serializers.CharField(required=False)
    since = serializers.DateTimeField(required=False)
    until = serializers.DateTimeField(required=False)
