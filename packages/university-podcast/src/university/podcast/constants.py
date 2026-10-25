from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

PODCAST_SCOPE = "podcast"
SHOW_CONTENT_TYPE = "podcast.show"
EPISODE_CONTENT_TYPE = "podcast.episode"
EPISODE_MEDIA_PURPOSE = "podcast.episode"
CLIP_MEDIA_PURPOSE = "podcast.clip"
COVER_MEDIA_PURPOSE = "podcast.cover"


class ShowStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PUBLISHED = "published", _("Published")
    ARCHIVED = "archived", _("Archived")


class ShowVisibility(models.TextChoices):
    PUBLIC = "public", _("Public")
    UNLISTED = "unlisted", _("Unlisted")
    AUDIENCE = "audience", _("Members of the host only")


class MemberRole(models.TextChoices):
    OWNER = "owner", _("Owner")
    HOST = "host", _("Host")
    PRODUCER = "producer", _("Producer")


MEMBER_RANK = {MemberRole.PRODUCER: 1, MemberRole.HOST: 2, MemberRole.OWNER: 3}


class EpisodeStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    SCHEDULED = "scheduled", _("Scheduled")
    PUBLISHED = "published", _("Published")
    UNPUBLISHED = "unpublished", _("Unpublished")


class EpisodeType(models.TextChoices):
    FULL = "full", _("Full")
    TRAILER = "trailer", _("Trailer")
    BONUS = "bonus", _("Bonus")


class TranscriptFormat(models.TextChoices):
    VTT = "vtt", _("WebVTT")
    SRT = "srt", _("SubRip")
    TEXT = "text", _("Plain text")


class TranscriptStatus(models.TextChoices):
    PENDING = "pending", _("Generating")
    READY = "ready", _("Ready")
    FAILED = "failed", _("Failed")
