from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class Visibility(models.TextChoices):
    PUBLIC = "public", _("Everyone")
    FOLLOWERS = "followers", _("Followers")
    PRIVATE = "private", _("Only me")
    INSTITUTION = "institution", _("My institution")
    CAMPUS = "campus", _("My campus")
    COMMUNITY = "community", _("A community")


class ContentStatus(models.TextChoices):
    PUBLISHED = "published", _("Published")
    #: Held by the anti-spam filter; visible to the author only until reviewed.
    PENDING_REVIEW = "pending_review", _("Pending review")
    HIDDEN = "hidden", _("Hidden by a moderator")


class FollowStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    PENDING = "pending", _("Pending approval")


class MentionPolicy(models.TextChoices):
    EVERYONE = "everyone", _("Everyone")
    FOLLOWING = "following", _("People I follow")
    NOBODY = "nobody", _("Nobody")
