"""Read-side rules for podcasts and episodes."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone

from university.core.audiences import is_member, member_scopes
from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.permissions.scopes import Scope
from university.permissions.services import has_permission
from university.podcast.constants import PODCAST_SCOPE, EpisodeStatus, ShowStatus, ShowVisibility
from university.podcast.models import Episode, Podcast, PodcastMember


def podcast_scope(podcast: Podcast) -> Scope:
    return Scope(PODCAST_SCOPE, str(podcast.pk))


def can_manage(user: Any, podcast: Podcast) -> bool:
    return has_permission(user, "podcast.manage", podcast_scope(podcast))


def member_role(user: Any, podcast: Podcast) -> str | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return PodcastMember.objects.filter(podcast=podcast, user=user).values_list("role", flat=True).first()


def can_view_podcast(user: Any, podcast: Podcast) -> bool:
    if podcast.deleted_at is not None:
        return False
    if podcast.status == ShowStatus.DRAFT or podcast.hidden_at is not None:
        return can_manage(user, podcast)
    if podcast.visibility == ShowVisibility.AUDIENCE and not is_member(user, podcast.scope_type, podcast.scope_id):
        return can_manage(user, podcast)
    return True


def episode_is_live(episode: Episode) -> bool:
    return (
        episode.deleted_at is None
        and episode.hidden_at is None
        and episode.status == EpisodeStatus.PUBLISHED
        and (episode.published_at is None or episode.published_at <= timezone.now())
    )


def can_view_episode(user: Any, episode: Episode) -> bool:
    podcast = episode.podcast
    if not can_view_podcast(user, podcast):
        return False
    return episode_is_live(episode) or can_manage(user, podcast)


def get_podcast(lookup: Any) -> Podcast:
    qs = Podcast.objects.all()
    podcast = qs.filter(pk=lookup).first() if is_valid_uuid(lookup) else qs.filter(slug=str(lookup)).first()
    if podcast is None:
        raise NotFound("Podcast not found.")
    return podcast


def get_visible_podcast(user: Any, lookup: Any) -> Podcast:
    podcast = get_podcast(lookup)
    if not can_view_podcast(user, podcast):
        raise NotFound("Podcast not found.")
    return podcast


def get_visible_episode(user: Any, episode_id: Any) -> Episode:
    episode = (
        Episode.objects.select_related("podcast").filter(pk=episode_id).first() if is_valid_uuid(episode_id) else None
    )
    if episode is None or not can_view_episode(user, episode):
        raise NotFound("Episode not found.")
    return episode


def discover(user: Any, params: Mapping[str, Any]) -> QuerySet[Podcast]:
    scopes = member_scopes(user) if getattr(user, "is_authenticated", False) else frozenset()
    audience = Q(visibility=ShowVisibility.PUBLIC)
    for scope_type, scope_id in scopes:
        audience |= Q(visibility=ShowVisibility.AUDIENCE, scope_type=scope_type, scope_id=str(scope_id))
    qs = Podcast.objects.filter(status=ShowStatus.PUBLISHED, hidden_at__isnull=True).filter(audience)
    if q := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q) | Q(author_name__icontains=q))
    for field in ("category", "language"):
        if value := params.get(field):
            qs = qs.filter(**{field: value})
    if params.get("scope_type") and params.get("scope_id"):
        qs = qs.filter(scope_type=params["scope_type"], scope_id=str(params["scope_id"]))
    return qs.order_by("-subscriber_count", "-published_at")


def live_episodes(podcast: Podcast) -> QuerySet[Episode]:
    return Episode.objects.filter(
        podcast=podcast, status=EpisodeStatus.PUBLISHED, hidden_at__isnull=True, published_at__lte=timezone.now()
    ).order_by("-published_at")
