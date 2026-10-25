from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

CAMPAIGN_CONTENT_TYPE = "creator.campaign"


class ProfileStatus(models.TextChoices):
    ACTIVE = "active", _("Active")
    #: Turned off by the creator; hidden everywhere.
    PAUSED = "paused", _("Paused")


class VerificationStatus(models.TextChoices):
    UNVERIFIED = "unverified", _("Unverified")
    PENDING = "pending", _("Pending review")
    VERIFIED = "verified", _("Verified")
    REVOKED = "revoked", _("Revoked")


class RequestStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    APPROVED = "approved", _("Approved")
    REJECTED = "rejected", _("Rejected")
    WITHDRAWN = "withdrawn", _("Withdrawn")


class OwnershipStatus(models.TextChoices):
    #: Waiting for the creator to place the challenge code in their bio.
    UNVERIFIED = "unverified", _("Unverified")
    #: The provider can't look profiles up; a reviewer must confirm.
    PENDING_REVIEW = "pending_review", _("Pending review")
    VERIFIED = "verified", _("Verified")


class CountSource(models.TextChoices):
    SELF_REPORTED = "self_reported", _("Self-reported")
    PROVIDER = "provider", _("From the platform")
    REVIEWER = "reviewer", _("Confirmed by a reviewer")


#: Follower counts trusted for campaign requirements.
TRUSTED_COUNT_SOURCES = frozenset({CountSource.PROVIDER, CountSource.REVIEWER})


class KitVisibility(models.TextChoices):
    PUBLIC = "public", _("Public")
    #: Anyone with the link (the kit's share token).
    UNLISTED = "unlisted", _("Anyone with the link")
    PRIVATE = "private", _("Only me")


class CampaignStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    OPEN = "open", _("Open for applications")
    CLOSED = "closed", _("Closed")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


class CampaignVisibility(models.TextChoices):
    PUBLIC = "public", _("Public")
    #: Not listed; creators join by invitation only.
    INVITE_ONLY = "invite_only", _("Invitation only")


class ParticipationStatus(models.TextChoices):
    INVITED = "invited", _("Invited")
    APPLIED = "applied", _("Applied")
    SHORTLISTED = "shortlisted", _("Shortlisted")
    ACCEPTED = "accepted", _("Accepted")
    DECLINED = "declined", _("Declined")
    WITHDRAWN = "withdrawn", _("Withdrawn")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")


OPEN_PARTICIPATION = frozenset(
    {ParticipationStatus.INVITED, ParticipationStatus.APPLIED, ParticipationStatus.SHORTLISTED}
)


class DeliverableStatus(models.TextChoices):
    PENDING = "pending", _("Pending")
    SUBMITTED = "submitted", _("Submitted")
    CHANGES_REQUESTED = "changes_requested", _("Changes requested")
    APPROVED = "approved", _("Approved")


#: Daily analytics metrics (aggregates only).
class Metric(models.TextChoices):
    FOLLOWERS_GAINED = "followers_gained", _("Followers gained")
    FOLLOWERS_LOST = "followers_lost", _("Followers lost")
    POSTS_PUBLISHED = "posts_published", _("Posts published")
    REACTIONS_RECEIVED = "reactions_received", _("Reactions received")
    COMMENTS_RECEIVED = "comments_received", _("Comments received")
    REPOSTS_RECEIVED = "reposts_received", _("Reposts received")
    MENTIONS = "mentions", _("Mentions")
    PROFILE_VIEWS = "profile_views", _("Creator profile views")
    MEDIA_KIT_VIEWS = "media_kit_views", _("Media kit views")
