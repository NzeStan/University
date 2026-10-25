"""Content adapters for shows and episodes — moderatable, with an explicit policy.

* **Who investigates**: the host scope's moderators (an institution's or a
  community's), otherwise platform moderators.
* **Which actions**: ``hide`` (managers only; can't be republished while
  hidden), ``restore``, and ``remove`` (soft-deletes; an episode's media is
  released). User-level sanctions apply to the show's owner / the episode's
  creator under moderation's usual rules.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.core.content import ContentAdapter, ContentRef
from university.core.ids import is_valid_uuid
from university.podcast.constants import EPISODE_CONTENT_TYPE, SHOW_CONTENT_TYPE


class _Hideable(ContentAdapter):
    moderatable = True

    def _get(self, object_id: Any) -> Any:
        raise NotImplementedError

    def hide(self, object_id: Any, *, reason: str) -> None:
        obj = self._get(object_id)
        if obj is not None and obj.hidden_at is None:
            obj.hidden_at = timezone.now()
            obj.hidden_reason = reason[:255]
            obj.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])

    def restore(self, object_id: Any) -> None:
        obj = self._get(object_id)
        if obj is not None and obj.hidden_at is not None:
            obj.hidden_at = None
            obj.hidden_reason = ""
            obj.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])


class ShowAdapter(_Hideable):
    content_type = SHOW_CONTENT_TYPE
    label = "Podcast"

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.podcast.models import Podcast

        qs = Podcast.objects.filter(status="published", hidden_at__isnull=True)
        return (str(pk) for pk in qs.values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Any:
        from university.podcast.models import Podcast

        return Podcast.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        podcast = self._get(object_id)
        if podcast is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(podcast.pk),
            author_id=str(podcast.owner_id) if podcast.owner_id else None,
            scope=podcast.host_scope,
            excerpt=f"{podcast.title}\n{podcast.description}"[:500],
            status="hidden" if podcast.hidden_at else podcast.status,
            created_at=podcast.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.podcast.selectors import can_view_podcast

        podcast = self._get(object_id)
        return podcast is not None and can_view_podcast(viewer, podcast)

    @transaction.atomic
    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.podcast.services import delete_episode_records

        podcast = self._get(object_id)
        if podcast is None:
            return
        for episode in podcast.episodes.all():
            delete_episode_records(episode)
        podcast.delete()


class EpisodeAdapter(_Hideable):
    content_type = EPISODE_CONTENT_TYPE
    label = "Podcast episode"

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.podcast.models import Episode

        qs = Episode.objects.filter(status="published", hidden_at__isnull=True)
        return (str(pk) for pk in qs.values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Any:
        from university.podcast.models import Episode

        return (
            Episode.objects.select_related("podcast").filter(pk=object_id).first() if is_valid_uuid(object_id) else None
        )

    def resolve(self, object_id: Any) -> ContentRef | None:
        episode = self._get(object_id)
        if episode is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(episode.pk),
            author_id=str(episode.created_by_id) if episode.created_by_id else None,
            scope=episode.podcast.host_scope,
            excerpt=f"{episode.title}\n{episode.summary}"[:500],
            status="hidden" if episode.hidden_at else episode.status,
            created_at=episode.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.podcast.selectors import can_view_episode

        episode = self._get(object_id)
        return episode is not None and can_view_episode(viewer, episode)

    @transaction.atomic
    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.podcast.services import delete_episode_records

        episode = self._get(object_id)
        if episode is not None:
            delete_episode_records(episode)
