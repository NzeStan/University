from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.serializers import StrictModelSerializer
from university.security.models import APIKey, ExternalIdentity, UserSession


class LoginSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254, help_text="Email, handle or verified phone number.")
    password = serializers.CharField(max_length=4096, trim_whitespace=False, style={"input_type": "password"})
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)


class ChallengeCompleteSerializer(serializers.Serializer):
    challenge_id = serializers.UUIDField()
    code = serializers.CharField(max_length=12)
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)


class RefreshSerializer(serializers.Serializer):
    refresh = serializers.CharField(max_length=256)


class PasswordlessRequestSerializer(serializers.Serializer):
    identifier = serializers.CharField(max_length=254)


class ProviderLoginSerializer(serializers.Serializer):
    id_token = serializers.CharField(max_length=8192, required=False)
    code = serializers.CharField(max_length=2048, required=False)
    nonce = serializers.CharField(max_length=256, required=False)
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)


class TokenPairSerializer(serializers.Serializer):
    token_type = serializers.CharField()
    access = serializers.CharField()
    refresh = serializers.CharField()
    access_expires_at = serializers.DateTimeField()
    refresh_expires_at = serializers.DateTimeField()
    session_id = serializers.UUIDField()


class MFAChallengeSerializer(serializers.Serializer):
    mfa_required = serializers.BooleanField()
    challenge_id = serializers.UUIDField()
    channel = serializers.CharField()
    destination = serializers.CharField()


class SessionSerializer(StrictModelSerializer):
    current = serializers.SerializerMethodField()

    class Meta:
        model = UserSession
        fields = (
            "id",
            "auth_method",
            "device_name",
            "user_agent",
            "ip_address",
            "created_at",
            "last_seen_at",
            "expires_at",
            "revoked_at",
            "current",
        )
        read_only_fields = fields

    def get_current(self, obj: UserSession) -> bool:
        return obj.pk == self.context.get("current_session_id")


class APIKeySerializer(StrictModelSerializer):
    class Meta:
        model = APIKey
        fields = (
            "id",
            "name",
            "lookup",
            "scopes",
            "allowed_ips",
            "created_at",
            "last_used_at",
            "expires_at",
            "revoked_at",
        )
        read_only_fields = fields


class APIKeyCreateSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    scopes = serializers.ListField(child=serializers.CharField(max_length=100), min_length=1, max_length=100)
    allowed_ips = serializers.ListField(child=serializers.CharField(max_length=64), required=False, max_length=50)
    expires_at = serializers.DateTimeField(required=False, allow_null=True)


class APIKeyCreatedSerializer(APIKeySerializer):
    key = serializers.SerializerMethodField(help_text="Shown only once.")

    class Meta(APIKeySerializer.Meta):
        fields = (*APIKeySerializer.Meta.fields, "key")
        read_only_fields = fields

    def get_key(self, obj: Any) -> str:
        return self.context["raw_key"]


class ExternalIdentitySerializer(StrictModelSerializer):
    class Meta:
        model = ExternalIdentity
        fields = ("id", "provider", "email", "created_at", "last_login_at")
        read_only_fields = fields


class MFAEnrolSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=["email", "sms"])


class MFAConfirmSerializer(serializers.Serializer):
    channel = serializers.ChoiceField(choices=["email", "sms"])
    challenge_id = serializers.UUIDField()
    code = serializers.CharField(max_length=12)


class PasswordConfirmSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=4096, trim_whitespace=False, allow_blank=True)
