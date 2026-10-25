"""Analytics data model: daily counters only.

``MetricDaily`` rows hold a count per day, metric (an event name such as
``social.post.created``, or a derived metric such as ``views.social.post`` or
``active_users.daily``) and scope (empty for platform-wide). There are no user
ids, payloads or timestamps finer than a day.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class MetricDaily(models.Model):
    id = models.BigAutoField(primary_key=True)
    date = models.DateField()
    metric = models.CharField(max_length=100)
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    count = models.PositiveBigIntegerField(default=0)

    class Meta:
        verbose_name = _("daily metric")
        constraints = [
            models.UniqueConstraint(fields=["date", "metric", "scope_type", "scope_id"], name="univ_analytics_unique"),
        ]
        indexes = [
            models.Index(fields=["scope_type", "scope_id", "metric", "date"], name="univ_analytics_scope"),
            models.Index(fields=["metric", "date"], name="univ_analytics_metric"),
        ]

    def __str__(self) -> str:
        scope = f" {self.scope_type}:{self.scope_id}" if self.scope_type else ""
        return f"{self.date} {self.metric}{scope} = {self.count}"
