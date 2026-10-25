from __future__ import annotations

import datetime as dt

from django.utils import timezone

from university.social.conf import social_settings
from university.social.models import PostMedia


def orphan_media_cutoff() -> dt.datetime | None:
    hours = social_settings.get("ORPHAN_MEDIA_HOURS", 24)
    return None if hours is None else timezone.now() - dt.timedelta(hours=int(hours))


def purge_orphan_media(cutoff: dt.datetime, dry_run: bool) -> int:
    """Delete uploads that were never attached to a post."""
    qs = PostMedia.objects.filter(post__isnull=True, created_at__lt=cutoff)
    if dry_run:
        return qs.count()
    count = 0
    for media in qs.iterator(chunk_size=200):
        media.file.delete(save=False)
        media.delete()
        count += 1
    return count
