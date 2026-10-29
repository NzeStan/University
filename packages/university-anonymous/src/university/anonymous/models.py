"""Anonymous content model.

Design rules enforced here:

* **No author foreign key** on content or on :class:`Authorship`. The link
  exists only as a per-item keyed hash (``owner_token``) and an encrypted
  identity (``identity_cipher``).
* **Random UUIDv4 ids** regardless of ``IDS.UUID_VERSION`` — time-ordered
  UUIDv7 would leak creation time.
* **Coarsened timestamps** (``TIMESTAMP_PRECISION_SECONDS``) and no
  ``updated_at`` column — exact times aid deanonymisation by correlation.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.models import AllObjectsManager, SoftDeleteManager


def coarse_now() -> dt.datetime:
    from university.anonymous.conf import anonymous_settings

    precision = max(1, int(anonymous_settings.get("TIMESTAMP_PRECISION_SECONDS", 300)))
    now = timezone.now()
    epoch = int(now.timestamp())
    return dt.datetime.fromtimestamp(epoch - epoch % precision, tz=dt.UTC)


class ContentStatus(models.TextChoices):
    PUBLISHED = "published", _("Published")
    PENDING_REVIEW = "pending_review", _("Pending review")
    HIDDEN = "hidden", _("Hidden by a moderator")


class AnonymousBase(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    created_at = models.DateTimeField(default=coarse_now, editable=False)
    deleted_at = models.DateTimeField(null=True, blank=True, editable=False)

    objects = SoftDeleteManager()
    all_objects = AllObjectsManager()

    class Meta:
        abstract = True

    def delete(self, using: Any = None, keep_parents: bool = False) -> tuple[int, dict[str, int]]:  # type: ignore[override]
        self.deleted_at = timezone.now()
        self.save(update_fields=["deleted_at"])
        return 1, {self._meta.label: 1}

    def hard_delete(self) -> Any:
        return super().delete()


class AnonymousPost(AnonymousBase):
    body = models.TextField()
    visibility = models.CharField(max_length=16)
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED)
    moderation_reason = models.CharField(max_length=255, blank=True)
    comments_enabled = models.BooleanField(default=True)
    reaction_count = models.PositiveIntegerField(default=0)
    comment_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("anonymous post")
        indexes = [
            models.Index(fields=["scope_type", "scope_id", "status", "-created_at"], name="univ_anon_post_scope"),
            models.Index(fields=["visibility", "status", "-created_at"], name="univ_anon_post_visibility"),
        ]

    def __str__(self) -> str:
        return f"Anonymous post {self.pk}"


class AnonymousComment(AnonymousBase):
    post = models.ForeignKey(AnonymousPost, on_delete=models.CASCADE, related_name="comments")
    body = models.TextField()
    pseudonym = models.CharField(max_length=64)
    #: Same value for one author within one thread (keyed hash); differs across threads.
    thread_token = models.CharField(max_length=64)
    is_op = models.BooleanField(default=False)
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED)
    moderation_reason = models.CharField(max_length=255, blank=True)
    reaction_count = models.PositiveIntegerField(default=0)
    #: Order within the thread. Timestamps are coarsened for privacy, so they
    #: cannot order comments; this reveals only relative order, never time.
    position = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("anonymous comment")
        indexes = [models.Index(fields=["post", "position"], name="univ_anon_comment_thread")]
        constraints = [models.UniqueConstraint(fields=["post", "position"], name="univ_anon_comment_position")]

    def __str__(self) -> str:
        return f"Anonymous comment {self.pk}"


class Authorship(models.Model):
    """The protected authorship record — never serialised, never joined to users."""

    class Kind(models.TextChoices):
        POST = "post", _("Post")
        COMMENT = "comment", _("Comment")
        MESSAGE = "message", _("Inbox message")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    object_id = models.UUIDField()
    owner_token = models.CharField(max_length=64)
    identity_cipher = models.TextField()

    class Meta:
        verbose_name = _("anonymous authorship")
        constraints = [models.UniqueConstraint(fields=["kind", "object_id"], name="univ_anon_authorship_unique")]
        default_permissions = ()

    def __str__(self) -> str:
        return f"Authorship of {self.kind} {self.object_id}"


class AnonymousReaction(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(AnonymousPost, on_delete=models.CASCADE, related_name="reactions")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    kind = models.CharField(max_length=16)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="univ_anon_reaction_unique")]

    def __str__(self) -> str:
        return f"{self.kind} on {self.post_id}"


class HiddenPost(models.Model):
    """A viewer chose not to see a post (the safe alternative to blocking)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    post = models.ForeignKey(AnonymousPost, on_delete=models.CASCADE, related_name="+")
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")

    class Meta:
        constraints = [models.UniqueConstraint(fields=["post", "user"], name="univ_anon_hidden_unique")]

    def __str__(self) -> str:
        return f"Hidden {self.post_id}"


class RevealRequest(models.Model):
    """A request to learn who wrote an anonymous item (two-person rule)."""

    class Status(models.TextChoices):
        PENDING = "pending", _("Pending approval")
        APPROVED = "approved", _("Approved")
        DENIED = "denied", _("Denied")

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    requester = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    kind = models.CharField(max_length=8, choices=Authorship.Kind.choices)
    object_id = models.UUIDField()
    justification = models.TextField()
    case_reference = models.CharField(max_length=128, blank=True)
    status = models.CharField(max_length=16, choices=Status.choices, default=Status.PENDING)
    approver = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    decision_reason = models.CharField(max_length=500, blank=True)
    decided_at = models.DateTimeField(null=True, blank=True)
    expires_at = models.DateTimeField(null=True, blank=True)
    retrieval_count = models.PositiveIntegerField(default=0)
    created_at = models.DateTimeField(default=timezone.now, editable=False)

    class Meta:
        verbose_name = _("identity reveal request")
        default_permissions = ()
        indexes = [models.Index(fields=["status", "created_at"], name="univ_anon_reveal_queue")]
        constraints = [
            models.CheckConstraint(
                condition=Q(approver__isnull=True) | ~Q(approver=models.F("requester")),
                name="univ_anon_reveal_two_people",
            )
        ]

    def __str__(self) -> str:
        return f"Reveal request {self.pk} ({self.status})"


class AnonymousInbox(models.Model):
    """A person's anonymous inbox ("send me anonymous questions"). Off until its owner turns it on."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="anonymous_inbox")
    enabled = models.BooleanField(default=False)
    prompt = models.CharField(max_length=200, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("anonymous inbox")
        verbose_name_plural = _("anonymous inboxes")

    def __str__(self) -> str:
        return f"Anonymous inbox of {self.user_id}"


class AnonymousMessage(AnonymousBase):
    """An anonymous message to someone's inbox.

    Authorship lives only in :class:`Authorship` (kind ``message``). ``sender_token`` is a keyed hash
    of (inbox, sender): it lets the recipient block "whoever sent this" without learning who it
    is, and it can't link the same sender across different inboxes.
    """

    inbox = models.ForeignKey(AnonymousInbox, on_delete=models.CASCADE, related_name="messages")
    body = models.TextField()
    sender_token = models.CharField(max_length=64)
    status = models.CharField(max_length=16, choices=ContentStatus.choices, default=ContentStatus.PUBLISHED)
    moderation_reason = models.CharField(max_length=255, blank=True)
    read_at = models.DateTimeField(null=True, blank=True)
    answer = models.TextField(blank=True)
    answered_at = models.DateTimeField(null=True, blank=True)
    answer_public = models.BooleanField(default=False)

    class Meta:
        verbose_name = _("anonymous message")
        ordering = ["-created_at"]
        indexes = [
            models.Index(fields=["inbox", "status", "-created_at"], name="univ_anon_msg_inbox"),
            models.Index(fields=["inbox", "answer_public", "-answered_at"], name="univ_anon_msg_answers"),
        ]

    def __str__(self) -> str:
        return f"Anonymous message {self.pk}"


class BlockedSender(models.Model):
    """ "Block whoever sent this": future messages from that sender to this inbox are dropped."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    inbox = models.ForeignKey(AnonymousInbox, on_delete=models.CASCADE, related_name="blocked_senders")
    sender_token = models.CharField(max_length=64)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("blocked anonymous sender")
        constraints = [models.UniqueConstraint(fields=["inbox", "sender_token"], name="univ_anon_blocked_unique")]
        default_permissions = ()

    def __str__(self) -> str:
        return f"Blocked sender in {self.inbox_id}"
