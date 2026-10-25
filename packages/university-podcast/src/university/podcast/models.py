"""Podcast data model.

::

    Podcast ──┬── PodcastMember (owner / host / producer)
              ├── Season
              ├── Subscription
              └── Episode ──┬── EpisodeGuest
                            ├── Transcript
                            ├── Clip
                            └── EpisodeDailyStat (aggregates only)

Audio, video, covers and clips are media ids in Core's media library; this
module never stores or serves files itself.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.podcast.constants import (
    EpisodeStatus,
    EpisodeType,
    MemberRole,
    ShowStatus,
    ShowVisibility,
    TranscriptFormat,
    TranscriptStatus,
)

USER = settings.AUTH_USER_MODEL


class Podcast(BaseModel, SoftDeleteModel):
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=120, unique=True)
    description = models.TextField(blank=True)
    author_name = models.CharField(max_length=120, blank=True)
    category = models.CharField(max_length=40, default="Education")
    language = models.CharField(max_length=8, default="en")
    explicit = models.BooleanField(default=False)
    website = models.URLField(max_length=300, blank=True)
    cover_media_id = models.CharField(max_length=64, blank=True)
    owner = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    visibility = models.CharField(max_length=16, choices=ShowVisibility.choices, default=ShowVisibility.PUBLIC)
    status = models.CharField(max_length=16, choices=ShowStatus.choices, default=ShowStatus.DRAFT)
    published_at = models.DateTimeField(null=True, blank=True)
    subscriber_count = models.PositiveIntegerField(default=0)
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("podcast")
        indexes = [
            models.Index(fields=["status", "visibility", "-published_at"], name="univ_pod_discovery"),
            models.Index(fields=["scope_type", "scope_id"], name="univ_pod_scope"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=(Q(scope_type="") & Q(scope_id="")) | (~Q(scope_type="") & ~Q(scope_id="")),
                name="univ_pod_scope_consistent",
            ),
            models.CheckConstraint(
                condition=~Q(visibility=ShowVisibility.AUDIENCE) | ~Q(scope_type=""), name="univ_pod_audience_scope"
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def host_scope(self) -> tuple[str, str] | None:
        return (self.scope_type, self.scope_id) if self.scope_type else None


class PodcastMember(BaseModel):
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="members")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="podcast_memberships")
    role = models.CharField(max_length=16, choices=MemberRole.choices, default=MemberRole.HOST)

    class Meta:
        verbose_name = _("podcast member")
        constraints = [
            models.UniqueConstraint(fields=["podcast", "user"], name="univ_pod_member_unique"),
            models.UniqueConstraint(fields=["podcast"], condition=Q(role=MemberRole.OWNER), name="univ_pod_one_owner"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} {self.role} of {self.podcast_id}"


class Season(BaseModel):
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="seasons")
    number = models.PositiveSmallIntegerField()
    title = models.CharField(max_length=160, blank=True)
    description = models.TextField(blank=True)

    class Meta:
        verbose_name = _("season")
        ordering = ("number",)
        constraints = [models.UniqueConstraint(fields=["podcast", "number"], name="univ_pod_season_unique")]

    def __str__(self) -> str:
        return f"Season {self.number}"


class Episode(BaseModel, SoftDeleteModel):
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="episodes")
    season = models.ForeignKey(Season, null=True, blank=True, on_delete=models.SET_NULL, related_name="episodes")
    number = models.PositiveIntegerField(null=True, blank=True)
    title = models.CharField(max_length=200)
    slug = models.SlugField(max_length=120)
    summary = models.CharField(max_length=500, blank=True)
    show_notes = models.TextField(blank=True)
    episode_type = models.CharField(max_length=16, choices=EpisodeType.choices, default=EpisodeType.FULL)
    explicit = models.BooleanField(default=False)
    audio_media_id = models.CharField(max_length=64, blank=True)
    video_media_id = models.CharField(max_length=64, blank=True)
    duration_seconds = models.FloatField(null=True, blank=True)
    status = models.CharField(max_length=16, choices=EpisodeStatus.choices, default=EpisodeStatus.DRAFT)
    publish_at = models.DateTimeField(null=True, blank=True)
    published_at = models.DateTimeField(null=True, blank=True)
    created_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("episode")
        indexes = [
            models.Index(fields=["podcast", "status", "-published_at"], name="univ_pod_episode_feed"),
            models.Index(fields=["status", "publish_at"], name="univ_pod_episode_schedule"),
        ]
        constraints = [models.UniqueConstraint(fields=["podcast", "slug"], name="univ_pod_episode_slug")]

    def __str__(self) -> str:
        return self.title


class EpisodeGuest(BaseModel):
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="guests")
    name = models.CharField(max_length=120)
    bio = models.CharField(max_length=300, blank=True)
    #: Optional linked account; shown publicly only after the guest confirms.
    user = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="podcast_guest_spots")
    confirmed_at = models.DateTimeField(null=True, blank=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("episode guest")
        ordering = ("position", "created_at")

    def __str__(self) -> str:
        return self.name


class Transcript(BaseModel):
    episode = models.OneToOneField(Episode, on_delete=models.CASCADE, related_name="transcript")
    language = models.CharField(max_length=8, default="en")
    source_format = models.CharField(max_length=8, choices=TranscriptFormat.choices, default=TranscriptFormat.TEXT)
    text = models.TextField(blank=True)
    #: ``[{"start": 0.0, "end": 4.2, "text": "..."}]`` (empty for plain text).
    cues = models.JSONField(default=list, blank=True)
    status = models.CharField(max_length=16, choices=TranscriptStatus.choices, default=TranscriptStatus.READY)
    automatic = models.BooleanField(default=False)
    error = models.CharField(max_length=64, blank=True)

    class Meta:
        verbose_name = _("transcript")

    def __str__(self) -> str:
        return f"Transcript of {self.episode_id}"


class Clip(BaseModel):
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="clips")
    title = models.CharField(max_length=160)
    start_seconds = models.FloatField()
    end_seconds = models.FloatField()
    media_id = models.CharField(max_length=64)
    created_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("clip")
        constraints = [
            models.CheckConstraint(condition=Q(end_seconds__gt=F("start_seconds")), name="univ_pod_clip_range")
        ]

    def __str__(self) -> str:
        return self.title


class Subscription(models.Model):
    podcast = models.ForeignKey(Podcast, on_delete=models.CASCADE, related_name="subscriptions")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="podcast_subscriptions")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        verbose_name = _("podcast subscription")
        constraints = [models.UniqueConstraint(fields=["podcast", "user"], name="univ_pod_subscription_unique")]

    def __str__(self) -> str:
        return f"{self.user_id} → {self.podcast_id}"


class EpisodeDailyStat(models.Model):
    episode = models.ForeignKey(Episode, on_delete=models.CASCADE, related_name="daily_stats")
    date = models.DateField()
    plays = models.PositiveIntegerField(default=0)
    completions = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("episode daily stat")
        constraints = [models.UniqueConstraint(fields=["episode", "date"], name="univ_pod_stat_unique")]

    def __str__(self) -> str:
        return f"{self.episode_id} {self.date}"
