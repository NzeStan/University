from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

COMMUNITY_SCOPE = "community"


class Privacy(models.TextChoices):
    #: Anyone can see it and join instantly.
    PUBLIC = "public", _("Public")
    #: Anyone can see it; joining needs approval.
    RESTRICTED = "restricted", _("Restricted")
    #: Hidden from non-members; joining by invitation or invite link only.
    PRIVATE = "private", _("Private")


class CommunityStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    ARCHIVED = "archived", _("Archived")
    #: Suspended by platform moderation.
    SUSPENDED = "suspended", _("Suspended")


class Role(models.TextChoices):
    OWNER = "owner", _("Owner")
    ADMIN = "admin", _("Admin")
    MODERATOR = "moderator", _("Moderator")
    MEMBER = "member", _("Member")


ROLE_RANK = {Role.MEMBER: 1, Role.MODERATOR: 2, Role.ADMIN: 3, Role.OWNER: 4}
#: Rank of platform/parent-scope managers who are not the owner.
MANAGER_RANK = 5


class PostingPolicy(models.TextChoices):
    MEMBERS = "members", _("All members")
    MODERATORS = "moderators", _("Moderators and above")
    ADMINS = "admins", _("Admins and owner")


class CommentingPolicy(models.TextChoices):
    MEMBERS = "members", _("All members")
    MODERATORS = "moderators", _("Moderators and above")
    ADMINS = "admins", _("Admins and owner")
    DISABLED = "disabled", _("Nobody")


#: Minimum role rank each policy requires.
POLICY_MIN_RANK = {"members": 1, "moderators": 2, "admins": 3, "disabled": 99}


class MembershipStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    PENDING = "pending", _("Requested to join")
    INVITED = "invited", _("Invited")
    BANNED = "banned", _("Banned")
