from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.notifications.constants import Platform
from university.notifications.models import Notification, PushDevice
from university.notifications.rendering import actor_name, open_url, render_title, target_available
from university.notifications.verbs import get_verb
from university.users.refs import person_ref


class NotificationActorSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)


class NotificationTargetSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()
    #: False when the viewer can no longer open it (deleted, hidden, private); null when unknown.
    available = serializers.BooleanField(allow_null=True)


class NotificationSerializer(StrictModelSerializer):
    title = serializers.SerializerMethodField()
    actor = serializers.SerializerMethodField()
    target = serializers.SerializerMethodField()
    url = serializers.SerializerMethodField()
    is_read = serializers.SerializerMethodField()
    is_seen = serializers.SerializerMethodField()

    class Meta:
        model = Notification
        fields = (
            "id",
            "verb",
            "category",
            "title",
            "actor",
            "actor_count",
            "target",
            "data",
            "url",
            "is_read",
            "is_seen",
            "read_at",
            "created_at",
            "last_activity_at",
        )
        read_only_fields = fields

    def _viewer(self) -> Any:
        return self.context["request"].user

    def get_title(self, obj: Notification) -> str:
        return render_title(obj, self._viewer())

    def _show_actor(self, obj: Notification) -> bool:
        try:
            return get_verb(obj.verb).show_actor
        except Exception:
            return False

    @staticmethod
    def _actor_data(user: Any) -> dict[str, Any] | None:
        if user is None or not user.is_active or getattr(user, "anonymized_at", None):
            return None
        return {**person_ref(user), "display_name": actor_name(user)}

    @extend_schema_field(NotificationActorSerializer(allow_null=True))
    def get_actor(self, obj: Notification) -> dict[str, Any] | None:
        return self._actor_data(obj.actor) if self._show_actor(obj) else None

    @extend_schema_field(NotificationTargetSerializer(allow_null=True))
    def get_target(self, obj: Notification) -> dict[str, Any] | None:
        if not obj.target_type:
            return None
        return {"type": obj.target_type, "id": obj.target_id, "available": target_available(obj, self._viewer())}

    def get_url(self, obj: Notification) -> str:
        return open_url(obj)

    def get_is_read(self, obj: Notification) -> bool:
        return obj.read_at is not None

    def get_is_seen(self, obj: Notification) -> bool:
        return obj.seen_at is not None


class NotificationCountsSerializer(serializers.Serializer):
    unread = serializers.IntegerField()
    unseen = serializers.IntegerField()


class NotificationReadAllSerializer(serializers.Serializer):
    category = serializers.CharField(max_length=32, required=False)
    #: Only mark notifications up to this time (what the client displayed).
    before = serializers.DateTimeField(required=False)


class NotificationUpdatedSerializer(serializers.Serializer):
    updated = serializers.IntegerField()


class NotificationChannelSerializer(serializers.Serializer):
    #: False, True, "immediate" or "digest".
    default = serializers.JSONField()
    effective = serializers.JSONField()


class NotificationCategorySerializer(serializers.Serializer):
    key = serializers.CharField()
    label = serializers.CharField()
    mandatory = serializers.BooleanField()
    bypass_quiet_hours = serializers.BooleanField()
    channels = serializers.DictField(child=NotificationChannelSerializer())


class PushDeviceSerializer(StrictModelSerializer):
    token_suffix = serializers.SerializerMethodField()
    active = serializers.SerializerMethodField()

    class Meta:
        model = PushDevice
        fields = ("id", "platform", "name", "token_suffix", "active", "created_at", "last_seen_at")
        read_only_fields = fields

    def get_token_suffix(self, obj: PushDevice) -> str:
        return obj.token[-6:]

    def get_active(self, obj: PushDevice) -> bool:
        return obj.disabled_at is None


class PushDeviceRegisterSerializer(serializers.Serializer):
    platform = serializers.ChoiceField(choices=Platform.choices)
    token = serializers.CharField(max_length=4096, write_only=True)
    name = serializers.CharField(max_length=100, required=False, allow_blank=True, default="")


class PushDeviceUnregisterSerializer(serializers.Serializer):
    token = serializers.CharField(max_length=4096, write_only=True)
