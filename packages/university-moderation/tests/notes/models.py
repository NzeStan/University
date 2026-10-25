from django.conf import settings
from django.db import models

from university.core.models import BaseModel


class Note(BaseModel):
    """Stand-in content for tests (named or anonymous)."""

    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="+")
    body = models.TextField()
    anonymous = models.BooleanField(default=False)
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    hidden = models.BooleanField(default=False)
    removed = models.BooleanField(default=False)

    class Meta:
        app_label = "notes"
