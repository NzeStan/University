"""Trending data model: hourly signal buckets and computed scores (no user ids)."""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

#: The pseudo-signal counting distinct people engaging with an item (per dedupe window).
ACTORS_SIGNAL = "__actors__"


class TrendingSignal(models.Model):
    id = models.BigAutoField(primary_key=True)
    content_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    signal = models.CharField(max_length=32)
    hour = models.DateTimeField()
    count = models.PositiveIntegerField(default=0)

    class Meta:
        verbose_name = _("trending signal")
        constraints = [
            models.UniqueConstraint(
                fields=["content_type", "object_id", "signal", "hour"], name="univ_trend_signal_unique"
            )
        ]
        indexes = [models.Index(fields=["hour"], name="univ_trend_signal_hour")]

    def __str__(self) -> str:
        return f"{self.content_type}:{self.object_id} {self.signal}@{self.hour:%Y-%m-%d %H}h = {self.count}"


class TrendingScore(models.Model):
    id = models.BigAutoField(primary_key=True)
    content_type = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    #: The item's audience scope (empty for platform-wide), for scoped trending lists.
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    #: For author diversity only; empty for anonymous content.
    author_id = models.CharField(max_length=64, blank=True)
    score = models.FloatField()
    computed_at = models.DateTimeField()

    class Meta:
        verbose_name = _("trending score")
        constraints = [models.UniqueConstraint(fields=["content_type", "object_id"], name="univ_trend_score_unique")]
        indexes = [
            models.Index(fields=["content_type", "-score"], name="univ_trend_score_type"),
            models.Index(fields=["scope_type", "scope_id", "-score"], name="univ_trend_score_scope"),
        ]

    def __str__(self) -> str:
        return f"{self.content_type}:{self.object_id} {self.score:.3f}"
