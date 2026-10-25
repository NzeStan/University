"""The database backend's index.

Each row is one searchable item: its content type (``index``), id, title,
body (from the item's content adapter) and visibility tags. Tags are
evaluated at query time *and* every hit is re-checked with the content
adapter, so a stale or over-broad tag can never leak a result.
"""

from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _


class SearchEntry(models.Model):
    id = models.BigAutoField(primary_key=True)
    index = models.CharField(max_length=64)
    object_id = models.CharField(max_length=64)
    title = models.CharField(max_length=200, blank=True)
    body = models.TextField(blank=True)
    #: Space-delimited tags: " public " or " institution:<id> " or " restricted ".
    tags = models.TextField(default=" public ")
    #: For purging a person's content from the index; empty for anonymous content.
    author_id = models.CharField(max_length=64, blank=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = _("search entry")
        verbose_name_plural = _("search entries")
        constraints = [models.UniqueConstraint(fields=["index", "object_id"], name="univ_search_entry_unique")]
        indexes = [models.Index(fields=["author_id"], name="univ_search_author")]

    def __str__(self) -> str:
        return f"{self.index}:{self.object_id}"
