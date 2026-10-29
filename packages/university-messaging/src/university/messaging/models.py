from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel
from university.messaging.crypto import seal, unseal


class ConversationKind(models.TextChoices):
    DIRECT = "direct", _("Direct")
    GROUP = "group", _("Group")


class ParticipantState(models.TextChoices):
    ACTIVE = "active", _("Active")
    #: A conversation started by someone the participant hasn't accepted yet.
    REQUEST = "request", _("Message request")
    DECLINED = "declined", _("Declined")
    LEFT = "left", _("Left")


class Conversation(BaseModel):
    kind = models.CharField(max_length=8, choices=ConversationKind.choices)
    title = models.CharField(max_length=100, blank=True)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    #: For direct conversations: "<smaller id>:<larger id>", so each pair has one conversation.
    direct_key = models.CharField(max_length=80, null=True, blank=True, unique=True)
    last_message_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("conversation")

    def __str__(self) -> str:
        return f"{self.get_kind_display()} conversation {self.pk}"


class Participant(BaseModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="participants")
    user = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="conversation_memberships"
    )
    is_admin = models.BooleanField(default=False)
    state = models.CharField(max_length=10, choices=ParticipantState.choices, default=ParticipantState.ACTIVE)
    last_read_at = models.DateTimeField(null=True, blank=True)
    muted = models.BooleanField(default=False)
    archived = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("participant")
        constraints = [models.UniqueConstraint(fields=["conversation", "user"], name="univ_msg_participant_unique")]
        indexes = [models.Index(fields=["user", "state", "archived"], name="univ_msg_participant_inbox")]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.conversation_id}"


class MessageStatus(models.TextChoices):
    VISIBLE = "visible", _("Visible")
    DELETED = "deleted", _("Deleted by the sender")
    HIDDEN = "hidden", _("Removed by the moderators")


class Message(BaseModel):
    conversation = models.ForeignKey(Conversation, on_delete=models.CASCADE, related_name="messages")
    sender = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL, related_name="+")
    #: Encrypted at rest: use ``text`` to read or write it.
    body_cipher = models.TextField()
    reply_to = models.ForeignKey("self", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    status = models.CharField(max_length=10, choices=MessageStatus.choices, default=MessageStatus.VISIBLE)
    edited_at = models.DateTimeField(null=True, blank=True)
    deleted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("message")
        indexes = [models.Index(fields=["conversation", "-created_at"], name="univ_msg_conversation_time")]

    def __str__(self) -> str:
        return f"Message {self.pk}"

    @property
    def text(self) -> str:
        return unseal(self.body_cipher) if self.status == MessageStatus.VISIBLE else ""

    @text.setter
    def text(self, value: str) -> None:
        self.body_cipher = seal(value)


class MessagingSettings(BaseModel):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="messaging_settings")
    #: Off: nobody new can start a conversation (existing ones continue).
    allow_requests = models.BooleanField(default=True)

    class Meta:
        verbose_name = _("messaging settings")
        verbose_name_plural = _("messaging settings")

    def __str__(self) -> str:
        return f"Messaging settings for {self.user_id}"
