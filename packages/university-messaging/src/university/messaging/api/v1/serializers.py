from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.messaging.models import Message, Participant, ParticipantState
from university.users.refs import PersonRefSerializer, person_ref

PLACEHOLDERS = {"deleted": "This message was deleted.", "hidden": "This message was removed by the moderators."}


class MessagingMessageSerializer(serializers.Serializer):
    id = serializers.UUIDField(read_only=True)
    conversation = serializers.UUIDField(source="conversation_id", read_only=True)
    sender = serializers.SerializerMethodField()
    body = serializers.SerializerMethodField()
    status = serializers.CharField(read_only=True)
    reply_to = serializers.UUIDField(source="reply_to_id", read_only=True, allow_null=True)
    is_mine = serializers.SerializerMethodField()
    edited_at = serializers.DateTimeField(read_only=True, allow_null=True)
    created_at = serializers.DateTimeField(read_only=True)

    @extend_schema_field(PersonRefSerializer(allow_null=True))
    def get_sender(self, obj: Message) -> dict[str, Any] | None:
        return person_ref(obj.sender)

    def get_body(self, obj: Message) -> str:
        return obj.text if obj.status == "visible" else PLACEHOLDERS.get(obj.status, "")

    def get_is_mine(self, obj: Message) -> bool:
        viewer = self.context.get("viewer")
        return bool(viewer is not None and obj.sender_id == viewer.pk)


class MessagingConversationSerializer(serializers.Serializer):
    """A conversation as one participant sees it."""

    id = serializers.UUIDField(source="conversation_id", read_only=True)
    kind = serializers.CharField(source="conversation.kind", read_only=True)
    title = serializers.SerializerMethodField()
    participants = serializers.SerializerMethodField()
    state = serializers.CharField(read_only=True)
    is_admin = serializers.BooleanField(read_only=True)
    muted = serializers.BooleanField(read_only=True)
    archived = serializers.BooleanField(read_only=True)
    unread_count = serializers.SerializerMethodField()
    last_message = serializers.SerializerMethodField()
    last_message_at = serializers.DateTimeField(source="conversation.last_message_at", read_only=True, allow_null=True)

    def _others(self, obj: Participant) -> list[Participant]:
        cache = self.context.setdefault("_others", {})
        if obj.conversation_id not in cache:
            cache[obj.conversation_id] = list(
                obj.conversation.participants.exclude(user_id=obj.user_id)
                .exclude(state__in=[ParticipantState.LEFT, ParticipantState.DECLINED])
                .select_related("user")
            )
        return cache[obj.conversation_id]

    def get_title(self, obj: Participant) -> str:
        if obj.conversation.title:
            return obj.conversation.title
        names = [p.user.display_name or p.user.handle or "" for p in self._others(obj)]
        return ", ".join(n for n in names if n)[:100] or "Conversation"

    @extend_schema_field(PersonRefSerializer(many=True))
    def get_participants(self, obj: Participant) -> list[dict[str, Any] | None]:
        return [person_ref(p.user) for p in self._others(obj)]

    def get_unread_count(self, obj: Participant) -> int:
        return int(getattr(obj, "unread", 0) or 0)

    @extend_schema_field(MessagingMessageSerializer(allow_null=True))
    def get_last_message(self, obj: Participant) -> dict[str, Any] | None:
        message_id = getattr(obj, "last_message_id", None)
        if not message_id:
            return None
        message = Message.objects.select_related("sender").filter(pk=message_id).first()
        return MessagingMessageSerializer(message, context=self.context).data if message else None


class MessagingStartSerializer(serializers.Serializer):
    participant_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=49)
    body = serializers.CharField(max_length=20000)
    title = serializers.CharField(max_length=100, required=False, allow_blank=True)


class MessagingSendSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)
    reply_to = serializers.UUIDField(required=False, allow_null=True)


class MessagingEditSerializer(serializers.Serializer):
    body = serializers.CharField(max_length=20000)


class MessagingConversationUpdateSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=100, required=False, allow_blank=True)
    muted = serializers.BooleanField(required=False)
    archived = serializers.BooleanField(required=False)


class MessagingAddParticipantsSerializer(serializers.Serializer):
    user_ids = serializers.ListField(child=serializers.UUIDField(), min_length=1, max_length=49)


class MessagingUnreadSerializer(serializers.Serializer):
    conversations = serializers.IntegerField()
    messages = serializers.IntegerField()
    requests = serializers.IntegerField()


class MessagingSettingsSerializer(serializers.Serializer):
    allow_requests = serializers.BooleanField()
