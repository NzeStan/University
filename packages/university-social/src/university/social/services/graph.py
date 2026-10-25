"""The social graph: follow (with approval), block, mute and restrict.

Blocking is enforced server-side everywhere through Core hooks
(``users.can_view_profile``, ``users.can_interact``) and the visibility
selectors, so other modules respect blocks without importing social.
"""

from __future__ import annotations

from typing import Any

from django.db import IntegrityError, transaction

from university.core.events import publish
from university.core.exceptions import NotFound, ValidationError
from university.core.ratelimit import rate_limit
from university.social import events
from university.social.constants import FollowStatus
from university.social.models import Block, Follow, Mute, Restrict
from university.social.services.common import active_user, ensure_can_interact, profile_increment
from university.social.services.profiles import get_social_profile
from university.users.selectors import get_visible_user


def _counts(follower_id: Any, followee_id: Any, delta: int) -> None:
    profile_increment(follower_id, "following_count", delta)
    profile_increment(followee_id, "followers_count", delta)


def _not_self(actor: Any, target: Any) -> None:
    if actor.pk == target.pk:
        raise ValidationError("You can't do that to yourself.", code="self_action")


def _delete_follow(follow: Follow) -> None:
    deleted, _ = Follow.objects.filter(pk=follow.pk).delete()
    if deleted and follow.status == FollowStatus.ACTIVE:
        _counts(follow.follower_id, follow.followee_id, -1)


# ----------------------------------------------------------------- follows
@transaction.atomic
def follow_user(*, follower: Any, followee_id: Any) -> Follow:
    rate_limit("social_follow", key=str(follower.pk))
    target = get_visible_user(viewer=follower, user_id=followee_id)  # 404 if hidden or blocked
    _not_self(follower, target)
    ensure_can_interact(follower, target, "follow")
    existing = Follow.objects.filter(follower=follower, followee=target).first()
    if existing is not None:
        return existing
    status = FollowStatus.PENDING if get_social_profile(target).requires_follow_approval else FollowStatus.ACTIVE
    try:
        with transaction.atomic():
            follow = Follow.objects.create(follower=follower, followee=target, status=status)
    except IntegrityError:
        return Follow.objects.get(follower=follower, followee=target)
    payload = {"follow_id": follow.pk, "follower_id": follower.pk, "followee_id": target.pk}
    if status == FollowStatus.ACTIVE:
        _counts(follower.pk, target.pk, +1)
        publish(events.FOLLOW_CREATED, payload, actor=follower)
    else:
        publish(events.FOLLOW_REQUESTED, payload, actor=follower)
    return follow


@transaction.atomic
def unfollow_user(*, follower: Any, followee_id: Any) -> None:
    follow = Follow.objects.select_for_update().filter(follower=follower, followee_id=followee_id).first()
    if follow is not None:
        _delete_follow(follow)
        publish(events.FOLLOW_REMOVED, {"follower_id": follower.pk, "followee_id": followee_id}, actor=follower)


@transaction.atomic
def approve_follow_request(*, user: Any, follow_id: Any) -> Follow:
    follow = Follow.objects.select_for_update().filter(pk=follow_id, followee=user, status=FollowStatus.PENDING).first()
    if follow is None:
        raise NotFound("Follow request not found.")
    follow.status = FollowStatus.ACTIVE
    follow.save(update_fields=["status", "updated_at"])
    _counts(follow.follower_id, user.pk, +1)
    publish(
        events.FOLLOW_APPROVED,
        {"follow_id": follow.pk, "follower_id": follow.follower_id, "followee_id": user.pk},
        actor=user,
    )
    return follow


@transaction.atomic
def decline_follow_request(*, user: Any, follow_id: Any) -> None:
    deleted, _ = Follow.objects.filter(pk=follow_id, followee=user, status=FollowStatus.PENDING).delete()
    if not deleted:
        raise NotFound("Follow request not found.")


@transaction.atomic
def remove_follower(*, user: Any, follower_id: Any) -> None:
    follow = Follow.objects.select_for_update().filter(follower_id=follower_id, followee=user).first()
    if follow is not None:
        _delete_follow(follow)


# ------------------------------------------------------- block/mute/restrict
@transaction.atomic
def block_user(*, blocker: Any, target_id: Any) -> Block:
    target = active_user(target_id)
    _not_self(blocker, target)
    try:
        with transaction.atomic():
            block = Block.objects.create(blocker=blocker, blocked=target)
    except IntegrityError:
        return Block.objects.get(blocker=blocker, blocked=target)
    # A block severs the relationship in both directions.
    for follow in Follow.objects.select_for_update().filter(
        follower__in=[blocker, target], followee__in=[blocker, target]
    ):
        _delete_follow(follow)
    publish(events.BLOCK_CREATED, {"blocker_id": blocker.pk, "blocked_id": target.pk}, actor=blocker)
    return block


@transaction.atomic
def unblock_user(*, blocker: Any, target_id: Any) -> None:
    Block.objects.filter(blocker=blocker, blocked_id=target_id).delete()


def _edge(model: type, actor_field: str, target_field: str, actor: Any, target_id: Any) -> Any:
    target = active_user(target_id)
    _not_self(actor, target)
    obj, _ = model.objects.get_or_create(**{actor_field: actor, target_field: target})
    return obj


@transaction.atomic
def mute_user(*, muter: Any, target_id: Any) -> Mute:
    return _edge(Mute, "muter", "muted", muter, target_id)


@transaction.atomic
def unmute_user(*, muter: Any, target_id: Any) -> None:
    Mute.objects.filter(muter=muter, muted_id=target_id).delete()


@transaction.atomic
def restrict_user(*, restrictor: Any, target_id: Any) -> Restrict:
    return _edge(Restrict, "restrictor", "restricted", restrictor, target_id)


@transaction.atomic
def unrestrict_user(*, restrictor: Any, target_id: Any) -> None:
    Restrict.objects.filter(restrictor=restrictor, restricted_id=target_id).delete()
