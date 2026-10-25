from __future__ import annotations

from django.conf import settings
from django.db import models
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel


class Item(BaseModel, SoftDeleteModel):
    """Example model: UUID primary key, timestamps, soft deletion."""

    owner = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="__module___items")
    title = models.CharField(max_length=200)

    class Meta:
        verbose_name = _("item")
        indexes = [models.Index(fields=["owner", "-created_at"], name="univ___module___item_owner")]

    def __str__(self) -> str:
        return self.title
