"""Community services: lifecycle, membership, roles, invitations.

Authority is evaluated by the permissions engine at the community scope:
owners/admins/moderators hold their role's permissions implicitly
(``COMMUNITY.ROLE_PERMISSIONS``), and platform or parent-scope managers (e.g.
an institution's community managers) hold them through role assignments.

Role rules: actors act only on members ranked strictly below them, and can
grant only roles strictly below their own. Exactly one active owner exists
(database constraint); ownership moves only by explicit transfer.
"""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.db.models import F
from django.db.models.functions import Greatest
from django.utils import timezone
from django.utils.text import slugify

from university.audit.services import record as audit
from university.community import events
from university.community.conf import community_settings
from university.community.constants import (
    ROLE_RANK,
    CommentingPolicy,
    CommunityStatus,
    MembershipStatus,
    PostingPolicy,
    Privacy,
    Role,
)
from university.community.models import Community, CommunityInviteLink, CommunityMembership
from university.community.selectors import get_visible_community, membership, rank, scope_of
from university.core.audiences import is_member
from university.core.crypto import generate_token, keyed_hash
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.ratelimit import rate_limit
from university.permissions.scopes import Scope
from university.permissions.services import authorize, has_permission, invalidate_user_permissions

EDITABLE = (
    "name",
    "description",
    "rules",
    "kind",
    "privacy",
    "requires_scope_membership",
    "posting_policy",
    "commenting_policy",
)
INVITE_PURPOSE = "community-invite"


def _payload(community: Community, user_id: Any = None, **extra: Any) -> dict[str, Any]:
    payload = {"community_id": community.pk, **extra}
    if user_id is not None:
        payload["user_id"] = user_id
    return payload


def _count(community: Community, delta: int) -> None:
    value = F("member_count") + delta if delta > 0 else Greatest(F("member_count") + delta, 0)
    Community.objects.filter(pk=community.pk).update(member_count=value)


def _activate(member: CommunityMembership, role: str = Role.MEMBER) -> CommunityMembership:
    member.status = MembershipStatus.ACTIVE
    member.role = role
    member.joined_at = timezone.now()
    member.save(update_fields=["status", "role", "joined_at", "updated_at"])
    _count(member.community, +1)
    invalidate_user_permissions(member.user_id)
    return member


def _require_active(community: Community) -> None:
    if community.status != CommunityStatus.ACTIVE:
        raise Conflict("This community is not active.", code="community_inactive")


def _check_audience(user: Any, community: Community) -> None:
    if community.requires_scope_membership and not is_member(user, community.scope_type, community.scope_id):
        raise PermissionDenied("This community is limited to members of its institution.", code="not_audience_member")


def _check_membership_limit(user: Any) -> None:
    limit = int(community_settings.get("MAX_MEMBERSHIPS_PER_USER", 500))
    if CommunityMembership.objects.filter(user=user, status=MembershipStatus.ACTIVE).count() >= limit:
        raise ValidationError("You have joined the maximum number of communities.", code="membership_limit")


# --------------------------------------------------------------- lifecycle
def _validate(data: Mapping[str, Any]) -> None:
    if "kind" in data and data["kind"] not in community_settings.get("KINDS", []):
        raise ValidationError(details={"kind": ["Unknown community kind."]})
    if "privacy" in data and data["privacy"] not in Privacy.values:
        raise ValidationError(details={"privacy": ["Unknown privacy setting."]})
    if "posting_policy" in data and data["posting_policy"] not in PostingPolicy.values:
        raise ValidationError(details={"posting_policy": ["Unknown posting policy."]})
    if "commenting_policy" in data and data["commenting_policy"] not in CommentingPolicy.values:
        raise ValidationError(details={"commenting_policy": ["Unknown commenting policy."]})
    if "rules" in data and (
        not isinstance(data["rules"], list)
        or len(data["rules"]) > 30
        or not all(isinstance(r, str) for r in data["rules"])
    ):
        raise ValidationError(details={"rules": ["Provide up to 30 rules as text."]})


@transaction.atomic
def create_community(
    *, creator: Any, data: Mapping[str, Any], scope_type: str = "", scope_id: Any = "", official: bool = False
) -> Community:
    rate_limit("community_create", key=str(creator.pk))
    policy = community_settings.get("CREATION_POLICY", "verified_users")
    parent = Scope(scope_type, scope_id) if scope_type else None
    if policy == "permission" or official:
        authorize(creator, "community.create", parent, audit_denial=True)
    elif not creator.email_verified_at:
        raise PermissionDenied("Verify your email address to create communities.", code="email_not_verified")
    if parent is not None and not official and not is_member(creator, scope_type, scope_id):
        raise PermissionDenied(
            "You can only create communities for audiences you belong to.", code="not_audience_member"
        )
    owned = CommunityMembership.objects.filter(user=creator, role=Role.OWNER, status=MembershipStatus.ACTIVE).count()
    if owned >= int(community_settings.get("MAX_OWNED_COMMUNITIES", 10)):
        raise ValidationError("You own the maximum number of communities.", code="ownership_limit")
    data = dict(data)
    _validate(data)
    if data.get("requires_scope_membership") and parent is None:
        raise ValidationError(details={"requires_scope_membership": ["Requires a parent audience."]})
    name = str(data.get("name", "")).strip()
    if not 3 <= len(name) <= 120:
        raise ValidationError(details={"name": ["Use 3 to 120 characters."]})
    base = slugify(data.pop("slug", "") or name)[:90] or "community"
    slug, n = base, 2
    while Community.all_objects.filter(slug=slug).exists():
        slug, n = f"{base}-{n}", n + 1
    community = Community.objects.create(
        name=name,
        slug=slug,
        description=str(data.get("description", ""))[:5000],
        rules=data.get("rules", []),
        kind=data.get("kind", "interest"),
        privacy=data.get("privacy", Privacy.PUBLIC),
        scope_type=scope_type,
        scope_id=str(scope_id) if scope_type else "",
        requires_scope_membership=bool(data.get("requires_scope_membership")),
        posting_policy=data.get("posting_policy", PostingPolicy.MEMBERS),
        commenting_policy=data.get("commenting_policy", CommentingPolicy.MEMBERS),
        is_official=official,
        created_by=creator,
    )
    owner = CommunityMembership.objects.create(
        community=community, user=creator, role=Role.OWNER, status=MembershipStatus.PENDING
    )
    _activate(owner, Role.OWNER)
    community.refresh_from_db(fields=["member_count"])
    audit("community.created", actor=creator, target=community, scope=("community", community.pk))
    publish(events.COMMUNITY_CREATED, _payload(community, creator.pk), actor=creator)
    return community


@transaction.atomic
def update_community(*, actor: Any, community_id: Any, data: Mapping[str, Any]) -> Community:
    community = get_visible_community(actor, community_id)
    authorize(actor, "community.manage", scope_of(community), audit_denial=True)
    data = dict(data)
    unknown = set(data) - set(EDITABLE)
    if unknown:
        raise ValidationError(details={f: ["This field cannot be changed."] for f in sorted(unknown)})
    _validate(data)
    if data.get("requires_scope_membership") and not community.scope_type:
        raise ValidationError(details={"requires_scope_membership": ["Requires a parent audience."]})
    changed = [f for f, v in data.items() if getattr(community, f) != v]
    for field in changed:
        setattr(community, field, data[field])
    if changed:
        community.save(update_fields=[*changed, "updated_at"])
        audit(
            "community.updated",
            actor=actor,
            target=community,
            scope=("community", community.pk),
            metadata={"fields": changed},
        )
        publish(events.COMMUNITY_UPDATED, _payload(community, fields=changed), actor=actor)
    return community


@transaction.atomic
def set_official(*, actor: Any, community_id: Any, official: bool) -> Community:
    """Only managers of the *parent* scope may recognise a community as official."""
    community = get_visible_community(actor, community_id)
    if not community.scope_type:
        raise ValidationError("Only communities linked to an audience can be official.", code="no_parent_scope")
    authorize(actor, "community.manage", Scope(community.scope_type, community.scope_id), audit_denial=True)
    Community.objects.filter(pk=community.pk).update(is_official=official)
    community.is_official = official
    audit("community.official_changed", actor=actor, target=community, metadata={"official": official})
    return community


@transaction.atomic
def archive_community(*, actor: Any, community_id: Any, reason: str = "") -> Community:
    community = get_visible_community(actor, community_id)
    authorize(actor, "community.manage", scope_of(community), audit_denial=True)
    community.status = CommunityStatus.ARCHIVED
    community.status_reason = reason[:255]
    community.save(update_fields=["status", "status_reason", "updated_at"])
    audit("community.archived", actor=actor, target=community, scope=("community", community.pk))
    publish(events.COMMUNITY_ARCHIVED, _payload(community), actor=actor)
    return community


# --------------------------------------------------------------- joining
@transaction.atomic
def join_community(*, user: Any, community_id: Any) -> CommunityMembership:
    community = get_visible_community(user, community_id)
    _require_active(community)
    existing = CommunityMembership.objects.select_for_update().filter(community=community, user=user).first()
    if existing is not None:
        if existing.status == MembershipStatus.BANNED:
            raise PermissionDenied("You can't join this community.", code="banned")
        if existing.status == MembershipStatus.INVITED:
            return accept_invitation(user=user, community_id=community.pk)
        return existing
    if community.privacy == Privacy.PRIVATE:
        raise PermissionDenied("This community is invitation-only.", code="invitation_required")
    _check_audience(user, community)
    _check_membership_limit(user)
    status = MembershipStatus.ACTIVE if community.privacy == Privacy.PUBLIC else MembershipStatus.PENDING
    try:
        with transaction.atomic():
            member = CommunityMembership.objects.create(community=community, user=user, status=MembershipStatus.PENDING)
    except IntegrityError:  # a concurrent request joined first
        return CommunityMembership.objects.get(community=community, user=user)
    if status == MembershipStatus.ACTIVE:
        _activate(member)
        publish(events.MEMBER_JOINED, _payload(community, user.pk), actor=user)
    else:
        publish(events.MEMBER_REQUESTED, _payload(community, user.pk), actor=user)
    return member


@transaction.atomic
def leave_community(*, user: Any, community_id: Any) -> None:
    community = Community.objects.filter(pk=community_id).first() if community_id else None
    member = (
        CommunityMembership.objects.select_for_update().filter(community=community, user=user).first()
        if community
        else None
    )
    if member is None or member.status == MembershipStatus.BANNED:
        raise NotFound("Membership not found.")
    if member.role == Role.OWNER and member.status == MembershipStatus.ACTIVE:
        raise Conflict("Transfer ownership before leaving.", code="owner_must_transfer")
    was_active = member.status == MembershipStatus.ACTIVE
    member.delete()
    if was_active:
        _count(community, -1)
    invalidate_user_permissions(user.pk)
    publish(events.MEMBER_LEFT, _payload(community, user.pk), actor=user)


def _target(community: Community, user_id: Any) -> CommunityMembership:
    member = (
        CommunityMembership.objects.select_for_update(of=("self",))
        .select_related("user")
        .filter(community=community, user_id=user_id)
        .first()
    )
    if member is None:
        raise NotFound("Member not found.")
    return member


def _manage(actor: Any, community_id: Any) -> tuple[Community, int]:
    community = get_visible_community(actor, community_id)
    authorize(actor, "community.members.manage", scope_of(community), audit_denial=True)
    return community, rank(actor, community)


def _outranks(actor_rank: int, member: CommunityMembership) -> None:
    if ROLE_RANK.get(member.role, 0) >= actor_rank:
        raise PermissionDenied("You can't act on members with your role or higher.", code="insufficient_rank")


@transaction.atomic
def review_request(*, actor: Any, community_id: Any, user_id: Any, approve: bool) -> CommunityMembership | None:
    community, _ = _manage(actor, community_id)
    member = _target(community, user_id)
    if member.status != MembershipStatus.PENDING:
        raise Conflict("There is no pending request.", code="no_pending_request")
    if not approve:
        member.delete()
        return None
    _check_audience(member.user, community)
    _activate(member)
    audit("community.member.approved", actor=actor, target=member, scope=("community", community.pk))
    publish(events.MEMBER_JOINED, _payload(community, member.user_id), actor=actor)
    return member


@transaction.atomic
def remove_member(*, actor: Any, community_id: Any, user_id: Any, ban: bool = False, reason: str = "") -> None:
    community, actor_rank = _manage(actor, community_id)
    member = _target(community, user_id)
    if member.user_id == actor.pk:
        raise ValidationError("Use leave instead.", code="self_action")
    _outranks(actor_rank, member)
    was_active = member.status == MembershipStatus.ACTIVE
    if ban:
        member.status = MembershipStatus.BANNED
        member.role = Role.MEMBER
        member.status_reason = reason[:255]
        member.save(update_fields=["status", "role", "status_reason", "updated_at"])
    else:
        member.delete()
    if was_active:
        _count(community, -1)
    invalidate_user_permissions(user_id)
    audit(
        "community.member.banned" if ban else "community.member.removed",
        actor=actor,
        target_type="university_community.communitymembership",
        target_id=user_id,
        scope=("community", community.pk),
        metadata={"reason": reason[:255]},
    )
    publish(events.MEMBER_BANNED if ban else events.MEMBER_REMOVED, _payload(community, user_id), actor=actor)


@transaction.atomic
def ban_non_member(*, actor: Any, community_id: Any, user_id: Any, reason: str = "") -> CommunityMembership:
    """Pre-emptively ban a user who is not (or no longer) a member."""
    community, _ = _manage(actor, community_id)
    if not get_user_model().objects.filter(pk=user_id).exists():
        raise NotFound("User not found.")
    existing = CommunityMembership.objects.filter(community=community, user_id=user_id).first()
    if existing is not None:
        remove_member(actor=actor, community_id=community.pk, user_id=user_id, ban=True, reason=reason)
        return CommunityMembership.objects.get(pk=existing.pk)
    return CommunityMembership.objects.create(
        community=community, user_id=user_id, status=MembershipStatus.BANNED, status_reason=reason[:255]
    )


@transaction.atomic
def unban(*, actor: Any, community_id: Any, user_id: Any) -> None:
    community, _ = _manage(actor, community_id)
    deleted, _ = CommunityMembership.objects.filter(
        community=community, user_id=user_id, status=MembershipStatus.BANNED
    ).delete()
    if not deleted:
        raise NotFound("Ban not found.")


@transaction.atomic
def change_role(*, actor: Any, community_id: Any, user_id: Any, role: str) -> CommunityMembership:
    community, actor_rank = _manage(actor, community_id)
    if role not in Role.values or role == Role.OWNER:
        raise ValidationError(details={"role": ["Choose admin, moderator or member (use transfer for ownership)."]})
    member = _target(community, user_id)
    if member.status != MembershipStatus.ACTIVE:
        raise Conflict("Only active members can have roles.", code="not_active")
    _outranks(actor_rank, member)
    if ROLE_RANK[role] >= actor_rank:
        raise PermissionDenied("You can only grant roles below your own.", code="insufficient_rank")
    previous = member.role
    member.role = role
    member.save(update_fields=["role", "updated_at"])
    invalidate_user_permissions(member.user_id)
    audit(
        "community.role.changed",
        actor=actor,
        target=member,
        scope=("community", community.pk),
        metadata={"from": previous, "to": role},
    )
    publish(events.ROLE_CHANGED, _payload(community, member.user_id, role=role), actor=actor)
    return member


@transaction.atomic
def transfer_ownership(*, actor: Any, community_id: Any, user_id: Any) -> CommunityMembership:
    community = get_visible_community(actor, community_id)
    actor_rank = rank(actor, community)
    if actor_rank < ROLE_RANK[Role.OWNER]:
        raise PermissionDenied("Only the owner can transfer ownership.", code="not_owner")
    new_owner = _target(community, user_id)
    if new_owner.status != MembershipStatus.ACTIVE or new_owner.user_id == actor.pk:
        raise ValidationError("Choose another active member.", code="invalid_new_owner")
    current = (
        CommunityMembership.objects.select_for_update()
        .filter(community=community, role=Role.OWNER, status=MembershipStatus.ACTIVE)
        .first()
    )
    if current is not None:
        current.role = Role.ADMIN
        current.save(update_fields=["role", "updated_at"])
        invalidate_user_permissions(current.user_id)
    new_owner.role = Role.OWNER
    new_owner.save(update_fields=["role", "updated_at"])
    invalidate_user_permissions(new_owner.user_id)
    audit("community.ownership.transferred", actor=actor, target=community, metadata={"to": str(user_id)})
    publish(events.OWNERSHIP_TRANSFERRED, _payload(community, user_id), actor=actor)
    return new_owner


# ------------------------------------------------------------- invitations
@transaction.atomic
def invite(*, actor: Any, community_id: Any, user_id: Any) -> CommunityMembership:
    community, _ = _manage(actor, community_id)
    _require_active(community)
    user = get_user_model().objects.filter(pk=user_id, status="active").first()
    if user is None:
        raise NotFound("User not found.")
    from university.core.hooks import Hook, hooks

    if not hooks.allows(Hook.USER_CAN_INTERACT, actor, user, "community_invite"):
        raise NotFound("User not found.")  # blocked: indistinguishable from missing
    existing = CommunityMembership.objects.filter(community=community, user=user).first()
    if existing is not None:
        if existing.status == MembershipStatus.BANNED:
            raise Conflict("This user is banned from the community.", code="banned")
        return existing
    member = CommunityMembership.objects.create(
        community=community, user=user, status=MembershipStatus.INVITED, invited_by=actor
    )
    publish(events.MEMBER_INVITED, _payload(community, user.pk, invited_by=actor.pk), actor=actor)
    return member


@transaction.atomic
def accept_invitation(*, user: Any, community_id: Any) -> CommunityMembership:
    member = (
        CommunityMembership.objects.select_for_update(of=("self",))
        .select_related("community")
        .filter(community_id=community_id, user=user, status=MembershipStatus.INVITED)
        .first()
    )
    if member is None:
        raise NotFound("Invitation not found.")
    _require_active(member.community)
    _check_audience(user, member.community)
    _check_membership_limit(user)
    _activate(member)
    publish(events.MEMBER_JOINED, _payload(member.community, user.pk), actor=user)
    return member


@transaction.atomic
def decline_invitation(*, user: Any, community_id: Any) -> None:
    deleted, _ = CommunityMembership.objects.filter(
        community_id=community_id, user=user, status=MembershipStatus.INVITED
    ).delete()
    if not deleted:
        raise NotFound("Invitation not found.")


@transaction.atomic
def create_invite_link(
    *, actor: Any, community_id: Any, expires_in_hours: int = 168, max_uses: int | None = None
) -> tuple[CommunityInviteLink, str]:
    community, _ = _manage(actor, community_id)
    _require_active(community)
    max_hours = int(community_settings.get("INVITE_LINK_MAX_DAYS", 30)) * 24
    if not 1 <= int(expires_in_hours) <= max_hours:
        raise ValidationError(details={"expires_in_hours": [f"Between 1 and {max_hours} hours."]})
    code = generate_token(18)
    link = CommunityInviteLink.objects.create(
        community=community,
        code_hash=keyed_hash(code, purpose=INVITE_PURPOSE),
        created_by=actor,
        expires_at=timezone.now() + dt.timedelta(hours=int(expires_in_hours)),
        max_uses=max_uses,
    )
    audit("community.invite_link.created", actor=actor, target=link, scope=("community", community.pk))
    return link, code


@transaction.atomic
def revoke_invite_link(*, actor: Any, community_id: Any, link_id: Any) -> None:
    community, _ = _manage(actor, community_id)
    if not CommunityInviteLink.objects.filter(pk=link_id, community=community, revoked_at__isnull=True).update(
        revoked_at=timezone.now()
    ):
        raise NotFound("Invite link not found.")


@transaction.atomic
def join_with_code(*, user: Any, code: str) -> CommunityMembership:
    rate_limit("community_join_code", key=str(user.pk))
    link = (
        CommunityInviteLink.objects.select_for_update(of=("self",))
        .select_related("community")
        .filter(code_hash=keyed_hash((code or "").strip(), purpose=INVITE_PURPOSE))
        .first()
    )
    now = timezone.now()
    if (
        link is None
        or link.revoked_at is not None
        or link.expires_at <= now
        or (link.max_uses is not None and link.uses >= link.max_uses)
        or link.community.deleted_at is not None
    ):
        raise NotFound("This invite link is invalid or has expired.")
    community = link.community
    _require_active(community)
    existing = CommunityMembership.objects.select_for_update().filter(community=community, user=user).first()
    if existing is not None:
        if existing.status == MembershipStatus.BANNED:
            raise PermissionDenied("You can't join this community.", code="banned")
        if existing.status == MembershipStatus.ACTIVE:
            return existing
    else:
        existing = CommunityMembership.objects.create(community=community, user=user, status=MembershipStatus.PENDING)
    _check_audience(user, community)
    _check_membership_limit(user)
    CommunityInviteLink.objects.filter(pk=link.pk).update(uses=F("uses") + 1)
    _activate(existing)
    publish(events.MEMBER_JOINED, _payload(community, user.pk, via="invite_link"), actor=user)
    return existing


def can_manage_members(user: Any, community: Community) -> bool:
    return has_permission(user, "community.members.manage", scope_of(community))


__all__ = [
    "accept_invitation",
    "archive_community",
    "ban_non_member",
    "can_manage_members",
    "change_role",
    "create_community",
    "create_invite_link",
    "decline_invitation",
    "invite",
    "join_community",
    "join_with_code",
    "leave_community",
    "membership",
    "remove_member",
    "review_request",
    "revoke_invite_link",
    "set_official",
    "transfer_ownership",
    "unban",
    "update_community",
]
