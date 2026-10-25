"""User API serializers. Every writable field is listed explicitly."""

from __future__ import annotations

from typing import Any

from django.contrib.auth import get_user_model
from rest_framework import serializers

from university.core.api.serializers import StrictModelSerializer
from university.core.conf import university_settings
from university.users.models import NotificationSettings, PrivacySettings, SecuritySettings
from university.users.selectors import public_profile_extras
from university.users.services.preferences import get_privacy_settings


class RegisterSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=4096, trim_whitespace=False, style={"input_type": "password"})
    handle = serializers.CharField(max_length=40, required=False, allow_blank=True, allow_null=True)
    display_name = serializers.CharField(max_length=100, required=False, allow_blank=True)
    consents = serializers.DictField(child=serializers.BooleanField(), required=False)
    consent_version = serializers.CharField(max_length=32, required=False, allow_blank=True)
    device_id = serializers.CharField(max_length=128, required=False, allow_blank=True)
    device_name = serializers.CharField(max_length=100, required=False, allow_blank=True)


class TokenSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=1024)


class EmailSerializer(serializers.Serializer):
    email = serializers.EmailField(max_length=254)


class PasswordResetConfirmSerializer(serializers.Serializer):
    uid = serializers.CharField(max_length=64)
    token = serializers.CharField(max_length=128)
    new_password = serializers.CharField(max_length=4096, trim_whitespace=False)


class PasswordChangeSerializer(serializers.Serializer):
    current_password = serializers.CharField(max_length=4096, trim_whitespace=False)
    new_password = serializers.CharField(max_length=4096, trim_whitespace=False)


class AccessTokenSerializer(serializers.Serializer):
    access = serializers.CharField()
    access_expires_at = serializers.DateTimeField()


class EmailChangeSerializer(serializers.Serializer):
    new_email = serializers.EmailField(max_length=254)
    password = serializers.CharField(max_length=4096, trim_whitespace=False)


class PhoneRequestSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=32)


class PhoneConfirmSerializer(serializers.Serializer):
    phone_number = serializers.CharField(max_length=32)
    challenge_id = serializers.UUIDField()
    code = serializers.CharField(max_length=12)


class DeleteAccountSerializer(serializers.Serializer):
    password = serializers.CharField(max_length=4096, trim_whitespace=False, allow_blank=True)


class MeSerializer(StrictModelSerializer):
    """The authenticated user's own account. Only profile fields are writable."""

    email_verified = serializers.BooleanField(read_only=True)
    phone_verified = serializers.BooleanField(read_only=True)

    class Meta:
        model = get_user_model()
        fields = (
            "id",
            "email",
            "pending_email",
            "handle",
            "display_name",
            "phone_number",
            "email_verified",
            "phone_verified",
            "status",
            "locale",
            "timezone",
            "created_at",
            "last_login",
        )
        read_only_fields = (
            "id",
            "email",
            "pending_email",
            "phone_number",
            "email_verified",
            "phone_verified",
            "status",
            "created_at",
            "last_login",
        )
        extra_kwargs = {"handle": {"validators": []}}


class PublicProfileSerializer(StrictModelSerializer):
    """What other people may see. Contact details only when the owner allows."""

    email = serializers.SerializerMethodField()
    phone_number = serializers.SerializerMethodField()
    extras = serializers.SerializerMethodField()

    class Meta:
        model = get_user_model()
        fields = ("id", "handle", "display_name", "created_at", "email", "phone_number", "extras")
        read_only_fields = fields

    def _privacy(self, obj: Any) -> PrivacySettings:
        return get_privacy_settings(obj)

    def get_email(self, obj: Any) -> str | None:
        return obj.email if self._privacy(obj).show_email else None

    def get_phone_number(self, obj: Any) -> str | None:
        return obj.phone_number if obj.phone_verified and self._privacy(obj).show_phone else None

    def get_extras(self, obj: Any) -> dict[str, Any]:
        return public_profile_extras(obj, self.context.get("viewer"))


class PrivacySettingsSerializer(StrictModelSerializer):
    class Meta:
        model = PrivacySettings
        fields = (
            "profile_visibility",
            "show_email",
            "show_phone",
            "show_affiliations",
            "discoverable_by_email",
            "discoverable_by_phone",
            "searchable",
            "updated_at",
        )
        read_only_fields = ("updated_at",)


class NotificationSettingsSerializer(StrictModelSerializer):
    class Meta:
        model = NotificationSettings
        fields = (
            "in_app_enabled",
            "email_enabled",
            "push_enabled",
            "sms_enabled",
            "marketing_emails",
            "digest_frequency",
            "quiet_hours_start",
            "quiet_hours_end",
            "categories",
            "updated_at",
        )
        read_only_fields = ("updated_at",)

    def validate_categories(self, value: Any) -> dict[str, dict[str, bool]]:
        if not isinstance(value, dict) or len(value) > 100:
            raise serializers.ValidationError("Must be an object of categories.")
        clean: dict[str, dict[str, bool]] = {}
        for category, channels in value.items():
            if not isinstance(channels, dict):
                raise serializers.ValidationError("Each category must map channels to booleans.")
            clean[str(category)[:64]] = {
                str(ch)[:16]: bool(on) for ch, on in channels.items() if ch in ("in_app", "email", "push", "sms")
            }
        return clean


class SecuritySettingsSerializer(StrictModelSerializer):
    class Meta:
        model = SecuritySettings
        fields = ("login_alerts_enabled", "mfa_enabled", "mfa_channel", "mfa_enabled_at", "updated_at")
        read_only_fields = ("mfa_enabled", "mfa_channel", "mfa_enabled_at", "updated_at")


class ConsentSerializer(serializers.Serializer):
    purpose = serializers.CharField(max_length=64)
    granted = serializers.BooleanField()
    version = serializers.CharField(max_length=32, required=False, allow_blank=True)

    def validate_purpose(self, value: str) -> str:
        if value not in university_settings.get("USERS.CONSENT_PURPOSES", []):
            raise serializers.ValidationError("Unknown consent purpose.")
        return value


class StatusChangeSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=255)
    until = serializers.DateTimeField(required=False, allow_null=True)
