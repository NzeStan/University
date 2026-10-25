"""Community data model.

::

    Community ──┬── CommunityMembership (role + status; exactly one active owner)
                └── CommunityInviteLink (hashed codes, expiry, use limits)

A community may be linked to a parent scope (an institution, campus or
department via ``scope_type``/``scope_id``). The link makes the parent its
permission ancestor and, with ``requires_scope_membership``, restricts
joining to members of that audience — without importing the module that
defines it.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import Q
from django.utils.translation import gettext_lazy as _

from university.community.constants import (
    CommentingPolicy,
    CommunityStatus,
    MembershipStatus,
    PostingPolicy,
    Privacy,
    Role,
)
from university.core.models import BaseModel, SoftDeleteModel

USER = settings.AUTH_USER_MODEL


class Community(BaseModel, SoftDeleteModel):
    name = models.CharField(max_length=120)
    slug = models.SlugField(max_length=100, unique=True)
    description = models.TextField(blank=True)
    rules = models.JSONField(default=list, blank=True)
    kind = models.CharField(max_length=32, default="interest")
    privacy = models.CharField(max_length=16, choices=Privacy.choices, default=Privacy.PUBLIC)
    status = models.CharField(max_length=16, choices=CommunityStatus.choices, default=CommunityStatus.ACTIVE)
    status_reason = models.CharField(max_length=255, blank=True)
    #: Optional parent audience (e.g. an institution) — the community's permission ancestor.
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    requires_scope_membership = models.BooleanField(default=False)
    #: Recognised by the parent scope's managers (e.g. the official CS department community).
    is_official = models.BooleanField(default=False)
    #: Who may publish top-level posts into the community (social and anonymous).
    posting_policy = models.CharField(max_length=16, choices=PostingPolicy.choices, default=PostingPolicy.MEMBERS)
    #: Who may comment on posts in the community.
    commenting_policy = models.CharField(
        max_length=16, choices=CommentingPolicy.choices, default=CommentingPolicy.MEMBERS
    )
    created_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    member_count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("community")
        verbose_name_plural = _("communities")
        indexes = [
            models.Index(fields=["status", "privacy", "-member_count"], name="univ_comm_discovery"),
            models.Index(fields=["scope_type", "scope_id"], name="univ_comm_scope"),
            models.Index(fields=["kind"], name="univ_comm_kind"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(scope_type="") & Q(scope_id="")) | (~Q(scope_type="") & ~Q(scope_id="")),
                name="univ_comm_scope_consistent",
            ),
            models.CheckConstraint(
                condition=Q(requires_scope_membership=False) | ~Q(scope_type=""),
                name="univ_comm_scope_membership_needs_scope",
            ),
        ]

    def __str__(self) -> str:
        return self.name

    @property
    def parent_scope(self) -> tuple[str, str] | None:
        return (self.scope_type, self.scope_id) if self.scope_type else None


class CommunityMembership(BaseModel):
    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="memberships")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="community_memberships")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.MEMBER)
    status = models.CharField(max_length=16, choices=MembershipStatus.choices, default=MembershipStatus.ACTIVE)
    invited_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    joined_at = models.DateTimeField(null=True, blank=True)
    status_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("community membership")
        constraints = [
            models.UniqueConstraint(fields=["community", "user"], name="univ_comm_membership_unique"),
            models.UniqueConstraint(
                fields=["community"],
                condition=Q(role=Role.OWNER, status=MembershipStatus.ACTIVE),
                name="univ_comm_one_owner",
            ),
        ]
        indexes = [
            models.Index(fields=["user", "status"], name="univ_comm_member_user"),
            models.Index(fields=["community", "status", "role"], name="univ_comm_member_comm"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} in {self.community_id} ({self.role}, {self.status})"


class CommunityInviteLink(BaseModel):
    """A shareable invite code. Only a keyed hash of the code is stored."""

    community = models.ForeignKey(Community, on_delete=models.CASCADE, related_name="invite_links")
    code_hash = models.CharField(max_length=64, unique=True)
    created_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    expires_at = models.DateTimeField()
    max_uses = models.PositiveIntegerField(null=True, blank=True)
    uses = models.PositiveIntegerField(default=0)
    revoked_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        verbose_name = _("community invite link")

    def __str__(self) -> str:
        return f"Invite link for {self.community_id}"
