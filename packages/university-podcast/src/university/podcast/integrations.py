"""Core hook implementations: member grants, scope parents, export and purge."""

from __future__ import annotations

from typing import Any

from university.core.ids import is_valid_uuid
from university.podcast.constants import PODCAST_SCOPE, MemberRole

ROLE_PERMISSIONS: dict[str, list[str]] = {
    MemberRole.OWNER: ["podcast.manage"],
    MemberRole.HOST: ["podcast.manage"],
    MemberRole.PRODUCER: ["podcast.manage"],
}


def implicit_grants(user: Any, scope: Any) -> list[str]:
    from university.podcast.models import PodcastMember

    if scope.type != PODCAST_SCOPE or not getattr(user, "is_authenticated", False) or not is_valid_uuid(scope.id):
        return []
    role = PodcastMember.objects.filter(podcast_id=scope.id, user=user).values_list("role", flat=True).first()
    return list(ROLE_PERMISSIONS.get(role, [])) if role else []


def implicit_scopes(user: Any, code: str) -> list[tuple[str, Any]]:
    from university.podcast.models import PodcastMember

    if not getattr(user, "is_authenticated", False) or code != "podcast.manage":
        return []
    return [
        (PODCAST_SCOPE, pid) for pid in PodcastMember.objects.filter(user=user).values_list("podcast_id", flat=True)
    ]


def podcast_parents(podcast_id: Any) -> list[tuple[str, Any]]:
    from university.podcast.models import Podcast

    if not is_valid_uuid(podcast_id):
        return []
    row = Podcast.all_objects.filter(pk=podcast_id).values_list("scope_type", "scope_id").first()
    return [row] if row and row[0] else []


def export_data(user: Any) -> dict[str, Any]:
    from university.podcast.models import EpisodeGuest, PodcastMember, Subscription

    return {
        "podcast_subscriptions": [
            s.podcast.title for s in Subscription.objects.filter(user=user).select_related("podcast")
        ],
        "podcast_memberships": [
            {"podcast": m.podcast.title, "role": m.role}
            for m in PodcastMember.objects.filter(user=user).select_related("podcast")
        ],
        "podcast_guest_spots": [
            {"episode": g.episode.title, "confirmed": g.confirmed_at is not None}
            for g in EpisodeGuest.objects.filter(user=user).select_related("episode")
        ],
    }


def purge(user_id: Any) -> None:
    """Subscriptions and guest links go; owned shows pass to the next member or are archived."""
    from django.db import transaction
    from django.db.models import F

    from university.podcast.constants import MEMBER_RANK, ShowStatus
    from university.podcast.models import EpisodeGuest, Podcast, PodcastMember, Subscription

    with transaction.atomic():
        for sub in Subscription.objects.filter(user_id=user_id):
            Podcast.objects.filter(pk=sub.podcast_id, subscriber_count__gt=0).update(
                subscriber_count=F("subscriber_count") - 1
            )
        Subscription.objects.filter(user_id=user_id).delete()
        EpisodeGuest.objects.filter(user_id=user_id).update(user=None, confirmed_at=None)
        for membership in PodcastMember.objects.filter(user_id=user_id, role=MemberRole.OWNER).select_related(
            "podcast"
        ):
            others = sorted(
                PodcastMember.objects.filter(podcast=membership.podcast).exclude(user_id=user_id),
                key=lambda m: -MEMBER_RANK.get(m.role, 0),
            )
            membership.delete()
            if others:
                others[0].role = MemberRole.OWNER
                others[0].save(update_fields=["role", "updated_at"])
                Podcast.objects.filter(pk=membership.podcast_id).update(owner_id=others[0].user_id)
            else:
                Podcast.objects.filter(pk=membership.podcast_id).update(status=ShowStatus.ARCHIVED, owner=None)
        PodcastMember.objects.filter(user_id=user_id).delete()
