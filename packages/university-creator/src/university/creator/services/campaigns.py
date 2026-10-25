"""Campaigns and sponsorships: briefs, applications, invitations, deals and deliverables.

::

    creator applies ─► applied ─► shortlisted ─► accepted ─► completed
    brand invites  ─► invited ───────────────────┘   │
                         └► declined / withdrawn      └► cancelled

Accepting is limited by the campaign's slots (row lock plus a database check).
Requirements (verified only, minimum verified reach) are enforced for both
applications and invitations. Fees are recorded here; paying them belongs to
a payments module.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.ratelimit import rate_limit
from university.creator import events
from university.creator.conf import creator_settings
from university.creator.constants import (
    CAMPAIGN_CONTENT_TYPE,
    OPEN_PARTICIPATION,
    CampaignStatus,
    CampaignVisibility,
    DeliverableStatus,
    ParticipationStatus,
    ProfileStatus,
)
from university.creator.models import Campaign, CreatorProfile, Deliverable, Participation
from university.creator.selectors import can_manage_campaign, get_campaign, get_visible_campaign, own_profile
from university.creator.services.profiles import resolve_categories, screen
from university.permissions.scopes import Scope
from university.permissions.services import authorize

P = ParticipationStatus
CAMPAIGN_FIELDS = (
    "brand_name",
    "title",
    "brief",
    "visibility",
    "slots",
    "budget_minor",
    "currency",
    "deliverables_summary",
    "application_deadline",
    "starts_on",
    "ends_on",
    "verified_only",
    "min_verified_reach",
    "disclosure_required",
)


def _audit(action: str, actor: Any, target: Any, **metadata: Any) -> None:
    audit(f"creator.{action}", actor=actor, target=target, category="creator", metadata=metadata)


def _locked(campaign_id: Any) -> Campaign:
    return Campaign.objects.select_for_update().get(pk=get_campaign(campaign_id).pk)


def _manage(actor: Any, campaign: Campaign) -> None:
    if not can_manage_campaign(actor, campaign):
        raise PermissionDenied("You can't manage this campaign.")


def _validate(campaign: Campaign) -> None:
    if campaign.currency not in creator_settings.get("CURRENCIES", []):
        raise ValidationError(details={"currency": ["Unsupported currency."]})
    if campaign.starts_on and campaign.ends_on and campaign.ends_on < campaign.starts_on:
        raise ValidationError(details={"ends_on": ["Must be on or after the start."]})
    if campaign.slots is not None and campaign.slots < max(campaign.accepted_count, 1):
        raise ValidationError(details={"slots": [f"{campaign.accepted_count} creators are already accepted."]})
    if campaign.visibility not in CampaignVisibility.values:
        raise ValidationError(details={"visibility": ["Unknown visibility."]})


def _payload(participation: Participation, **extra: Any) -> dict[str, Any]:
    return {
        "participation_id": participation.pk,
        "campaign_id": participation.campaign_id,
        "creator_user_id": participation.profile.user_id,
        "owner_id": participation.campaign.owner_id,
        "status": participation.status,
        **extra,
    }


# ---------------------------------------------------------------- campaigns
@transaction.atomic
def create_campaign(
    *, owner: Any, data: Mapping[str, Any], categories: Iterable[str] = (), scope_type: str = "", scope_id: Any = ""
) -> Campaign:
    rate_limit("creator_campaign_create", key=str(owner.pk))
    ensure_can_create(owner, CAMPAIGN_CONTENT_TYPE)
    scope_id = str(scope_id or "")
    if scope_type or scope_id:
        from university.core.registry import registry

        if not (scope_type and scope_id) or scope_type not in registry.scope_types:
            raise ValidationError(details={"scope_type": ["Unknown sponsor."]})
        authorize(owner, "creator.campaigns.manage", Scope(scope_type, scope_id), audit_denial=True)
    elif creator_settings.get("CAMPAIGN_POLICY") == "permission":
        authorize(owner, "creator.campaigns.manage", audit_denial=True)
    elif not owner.email_verified_at:
        raise PermissionDenied("Verify your email address to run campaigns.", code="email_not_verified")
    limit = int(creator_settings.get("MAX_OPEN_CAMPAIGNS_PER_USER", 10))
    active = Campaign.objects.filter(owner=owner, status__in=[CampaignStatus.DRAFT, CampaignStatus.OPEN]).count()
    if active >= limit:
        raise PermissionDenied(f"You can run up to {limit} active campaigns.", code="campaign_limit_reached")
    fields = {k: v for k, v in data.items() if k in CAMPAIGN_FIELDS}
    fields.setdefault("currency", creator_settings.get("DEFAULT_CURRENCY", "NGN"))
    fields.setdefault("disclosure_required", bool(creator_settings.get("DISCLOSURE_REQUIRED_BY_DEFAULT", True)))
    campaign = Campaign(owner=owner, scope_type=scope_type, scope_id=scope_id, **fields)
    _validate(campaign)
    screen(f"{campaign.brand_name}\n{campaign.title}\n{campaign.brief}", actor=owner, kind="campaign")
    campaign.save()
    campaign.categories.set(resolve_categories(categories))
    _audit("campaign.created", owner, campaign)
    return campaign


@transaction.atomic
def update_campaign(
    *, actor: Any, campaign_id: Any, data: Mapping[str, Any], categories: Iterable[str] | None = None
) -> Campaign:
    campaign = _locked(campaign_id)
    _manage(actor, campaign)
    if campaign.status in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
        raise Conflict("This campaign is finished.", code="campaign_finished")
    for key, value in data.items():
        if key in CAMPAIGN_FIELDS:
            setattr(campaign, key, value)
    _validate(campaign)
    screen(f"{campaign.brand_name}\n{campaign.title}\n{campaign.brief}", actor=actor, kind="campaign")
    campaign.save()
    if categories is not None:
        campaign.categories.set(resolve_categories(categories))
    return campaign


def _transition(actor: Any, campaign_id: Any, allowed: set[str], target: str, event: str) -> Campaign:
    campaign = _locked(campaign_id)
    _manage(actor, campaign)
    if campaign.status not in allowed:
        raise Conflict(f"A {campaign.status} campaign can't become {target}.", code="invalid_transition")
    if target == CampaignStatus.OPEN and campaign.hidden_at:
        raise PermissionDenied("This campaign was hidden by the moderators.", code="campaign_hidden")
    campaign.status = target
    now = timezone.now()
    if target == CampaignStatus.OPEN and not campaign.published_at:
        campaign.published_at = now
    if target in (CampaignStatus.CLOSED, CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
        campaign.closed_at = now
    campaign.save()
    _audit(f"campaign.{target}", actor, campaign)
    publish(event, {"campaign_id": campaign.pk, "owner_id": campaign.owner_id}, actor=actor)
    return campaign


@transaction.atomic
def publish_campaign(*, actor: Any, campaign_id: Any) -> Campaign:
    return _transition(
        actor,
        campaign_id,
        {CampaignStatus.DRAFT, CampaignStatus.CLOSED},
        CampaignStatus.OPEN,
        events.CAMPAIGN_PUBLISHED,
    )


@transaction.atomic
def close_campaign(*, actor: Any, campaign_id: Any) -> Campaign:
    return _transition(actor, campaign_id, {CampaignStatus.OPEN}, CampaignStatus.CLOSED, events.CAMPAIGN_CLOSED)


@transaction.atomic
def complete_campaign(*, actor: Any, campaign_id: Any) -> Campaign:
    return _transition(
        actor,
        campaign_id,
        {CampaignStatus.OPEN, CampaignStatus.CLOSED},
        CampaignStatus.COMPLETED,
        events.CAMPAIGN_COMPLETED,
    )


def cancel_campaign_records(campaign: Campaign, *, actor: Any = None, reason: str = "") -> None:
    """Cancel a campaign and its open participations (no authorisation; used by moderation)."""
    campaign.status = CampaignStatus.CANCELLED
    campaign.closed_at = timezone.now()
    campaign.save(update_fields=["status", "closed_at", "updated_at"])
    for participation in campaign.participations.select_related("profile").filter(
        status__in=[*OPEN_PARTICIPATION, P.ACCEPTED]
    ):
        participation.status = P.CANCELLED
        participation.note = reason[:500]
        _settle_fee(participation)
        participation.decided_at = timezone.now()
        participation.save(update_fields=["status", "note", "decided_at", "updated_at"])
        participation.campaign = campaign
        publish(events.PARTICIPATION_CHANGED, _payload(participation), actor=actor)
    publish(events.CAMPAIGN_CANCELLED, {"campaign_id": campaign.pk, "owner_id": campaign.owner_id}, actor=actor)


@transaction.atomic
def cancel_campaign(*, actor: Any, campaign_id: Any, reason: str = "") -> Campaign:
    campaign = _locked(campaign_id)
    _manage(actor, campaign)
    if campaign.status in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
        raise Conflict("This campaign is finished.", code="campaign_finished")
    cancel_campaign_records(campaign, actor=actor, reason=reason)
    _audit("campaign.cancelled", actor, campaign, reason=reason[:500])
    return campaign


# ------------------------------------------------------------ participation
def _check_requirements(campaign: Campaign, profile: CreatorProfile) -> None:
    if profile.status != ProfileStatus.ACTIVE:
        raise Conflict("This creator profile isn't active.", code="profile_inactive")
    if campaign.verified_only and not profile.is_verified:
        raise PermissionDenied("This campaign is for verified creators.", code="verified_only")
    if profile.verified_reach < campaign.min_verified_reach:
        raise PermissionDenied(
            "This campaign needs a larger verified audience.",
            code="reach_too_low",
            details={"required": campaign.min_verified_reach},
        )


@transaction.atomic
def apply(*, user: Any, campaign_id: Any, pitch: str, proposed_fee_minor: int | None = None) -> Participation:
    rate_limit("creator_campaign_apply", key=str(user.pk))
    profile = own_profile(user)
    visible = get_visible_campaign(user, campaign_id)
    campaign = _locked(visible.pk)
    if campaign.status != CampaignStatus.OPEN or campaign.visibility != CampaignVisibility.PUBLIC:
        raise Conflict("This campaign isn't taking applications.", code="campaign_not_open")
    if campaign.application_deadline and timezone.now() > campaign.application_deadline:
        raise Conflict("The application deadline has passed.", code="deadline_passed")
    if campaign.owner_id == user.pk:
        raise PermissionDenied("You can't apply to your own campaign.", code="own_campaign")
    if campaign.owner_id and not hooks.allows(Hook.USER_CAN_INTERACT, user, campaign.owner, "apply"):
        raise NotFound("Campaign not found.")
    _check_requirements(campaign, profile)
    pitch = (pitch or "").strip()
    if not 10 <= len(pitch) <= 3000:
        raise ValidationError(details={"pitch": ["Write a pitch of 10 to 3000 characters."]})
    screen(pitch, actor=user, kind="campaign_pitch")
    existing = Participation.objects.select_for_update().filter(campaign=campaign, profile=profile).first()
    if existing is not None:
        if existing.status in OPEN_PARTICIPATION | {P.ACCEPTED, P.COMPLETED}:
            raise Conflict("You're already part of this campaign.", code="already_participating")
        if existing.status == P.DECLINED:
            raise PermissionDenied("The brand declined your application.", code="declined")
        participation = existing  # Withdrawn or cancelled: apply again.
    else:
        participation = Participation(campaign=campaign, profile=profile)
    participation.status = P.APPLIED
    participation.pitch = pitch
    participation.proposed_fee_minor = proposed_fee_minor
    participation.decided_at = None
    participation.save()
    publish(events.PARTICIPATION_CHANGED, _payload(participation), actor=user)
    return participation


@transaction.atomic
def invite(*, actor: Any, campaign_id: Any, profile_id: Any, note: str = "") -> Participation:
    rate_limit("creator_campaign_invite", key=str(actor.pk))
    campaign = _locked(campaign_id)
    _manage(actor, campaign)
    if campaign.status not in (CampaignStatus.DRAFT, CampaignStatus.OPEN, CampaignStatus.CLOSED):
        raise Conflict("This campaign is finished.", code="campaign_finished")
    profile = CreatorProfile.objects.select_related("user").filter(pk=profile_id).first()
    if (
        profile is None
        or not profile.open_to_sponsorships
        or not hooks.allows(Hook.USER_CAN_INTERACT, actor, profile.user, "invite")
    ):
        raise NotFound("Creator not found.")
    if profile.user_id == actor.pk:
        raise ValidationError("You can't invite yourself.", code="self_invite")
    _check_requirements(campaign, profile)
    try:
        with transaction.atomic():
            participation = Participation.objects.create(
                campaign=campaign, profile=profile, status=P.INVITED, invited_by=actor, note=note[:500]
            )
    except IntegrityError:
        raise Conflict("This creator is already part of the campaign.", code="already_participating") from None
    _audit("participation.invited", actor, participation)
    publish(events.PARTICIPATION_CHANGED, _payload(participation), actor=actor)
    return participation


def _participation(participation_id: Any) -> tuple[Campaign, Participation]:
    found = Participation.objects.filter(pk=participation_id).first()
    if found is None:
        raise NotFound("Participation not found.")
    campaign = _locked(found.campaign_id)
    participation = Participation.objects.select_for_update().select_related("profile").get(pk=found.pk)
    participation.campaign = campaign
    return campaign, participation


def _accept(campaign: Campaign, participation: Participation, fee: int | None) -> None:
    if campaign.slots is not None and campaign.accepted_count >= campaign.slots:
        raise Conflict("All slots are filled.", code="slots_full")
    campaign.accepted_count += 1
    campaign.save(update_fields=["accepted_count", "updated_at"])
    participation.status = P.ACCEPTED
    participation.agreed_fee_minor = fee if fee is not None else participation.proposed_fee_minor


def _settle_fee(participation: Participation) -> None:
    """A paid fee goes to the creator on completion and back to the brand on cancellation."""
    from university.core.payables import REFUND_REQUESTED, RELEASE_REQUESTED

    if not participation.fee_paid_at:
        return
    target = {"purpose": "creator.participation", "object_id": participation.pk}
    if participation.status == P.COMPLETED:
        publish(RELEASE_REQUESTED, target)
    elif participation.status == P.CANCELLED:
        publish(REFUND_REQUESTED, {**target, "reason": "Collaboration cancelled"})


def _release_slot(campaign: Campaign) -> None:
    campaign.accepted_count = max(campaign.accepted_count - 1, 0)
    campaign.save(update_fields=["accepted_count", "updated_at"])


@transaction.atomic
def brand_decision(
    *, actor: Any, participation_id: Any, action: str, fee_minor: int | None = None, note: str = ""
) -> Participation:
    """The brand shortlists, accepts, declines, completes or cancels a participation."""
    campaign, participation = _participation(participation_id)
    _manage(actor, campaign)
    status = participation.status
    if action == "shortlist" and status == P.APPLIED:
        participation.status = P.SHORTLISTED
    elif action == "accept" and status in (P.APPLIED, P.SHORTLISTED):
        _accept(campaign, participation, fee_minor)
    elif action == "decline" and status in (P.APPLIED, P.SHORTLISTED, P.INVITED):
        participation.status = P.DECLINED
    elif action == "complete" and status == P.ACCEPTED:
        pending = participation.deliverables.exclude(status=DeliverableStatus.APPROVED).exists()
        if pending:
            raise Conflict("Approve every deliverable first.", code="deliverables_pending")
        participation.status = P.COMPLETED
    elif action == "cancel" and status == P.ACCEPTED:
        _release_slot(campaign)
        participation.status = P.CANCELLED
    else:
        raise Conflict(f"You can't {action} a {status} participation.", code="invalid_transition")
    participation.note = note[:500] or participation.note
    participation.decided_at = timezone.now()
    participation.save()
    _settle_fee(participation)
    _audit(f"participation.{action}", actor, participation)
    publish(events.PARTICIPATION_CHANGED, _payload(participation), actor=actor)
    return participation


@transaction.atomic
def creator_decision(*, user: Any, participation_id: Any, action: str, note: str = "") -> Participation:
    """The creator accepts or declines an invitation, withdraws, or cancels an accepted deal."""
    campaign, participation = _participation(participation_id)
    if participation.profile.user_id != user.pk:
        raise NotFound("Participation not found.")
    status = participation.status
    if action == "accept" and status == P.INVITED:
        if campaign.status in (CampaignStatus.COMPLETED, CampaignStatus.CANCELLED):
            raise Conflict("This campaign is finished.", code="campaign_finished")
        _accept(campaign, participation, None)
    elif action == "decline" and status == P.INVITED:
        participation.status = P.DECLINED
    elif action == "withdraw" and status in (P.APPLIED, P.SHORTLISTED):
        participation.status = P.WITHDRAWN
    elif action == "cancel" and status == P.ACCEPTED:
        _release_slot(campaign)
        participation.status = P.CANCELLED
    else:
        raise Conflict(f"You can't {action} a {status} participation.", code="invalid_transition")
    participation.note = note[:500] or participation.note
    participation.decided_at = timezone.now()
    participation.save()
    _settle_fee(participation)
    publish(events.PARTICIPATION_CHANGED, _payload(participation), actor=user)
    return participation


# ------------------------------------------------------------- deliverables
def _for_deliverables(actor: Any, participation_id: Any) -> tuple[Campaign, Participation, bool]:
    campaign, participation = _participation(participation_id)
    is_brand = can_manage_campaign(actor, campaign)
    if not is_brand and participation.profile.user_id != actor.pk:
        raise NotFound("Participation not found.")
    return campaign, participation, is_brand


@transaction.atomic
def add_deliverable(*, actor: Any, participation_id: Any, data: Mapping[str, Any]) -> Deliverable:
    _, participation, is_brand = _for_deliverables(actor, participation_id)
    if not is_brand:
        raise PermissionDenied("Only the brand adds deliverables.")
    if participation.status != P.ACCEPTED:
        raise Conflict("Deliverables are for accepted creators.", code="not_accepted")
    if participation.deliverables.count() >= int(creator_settings.get("MAX_DELIVERABLES", 30)):
        raise ValidationError("This collaboration has the maximum number of deliverables.", code="deliverable_limit")
    return Deliverable.objects.create(
        participation=participation,
        title=str(data.get("title", ""))[:160],
        description=str(data.get("description", ""))[:5000],
        due_at=data.get("due_at"),
    )


def _deliverable(actor: Any, deliverable_id: Any) -> tuple[Campaign, Deliverable, bool]:
    found = Deliverable.objects.filter(pk=deliverable_id).first()
    if found is None:
        raise NotFound("Deliverable not found.")
    campaign, participation, is_brand = _for_deliverables(actor, found.participation_id)
    deliverable = Deliverable.objects.select_for_update().get(pk=found.pk)
    deliverable.participation = participation
    return campaign, deliverable, is_brand


@transaction.atomic
def submit_deliverable(
    *, user: Any, deliverable_id: Any, url: str, note: str = "", disclosure_confirmed: bool = False
) -> Deliverable:
    campaign, deliverable, _ = _deliverable(user, deliverable_id)
    participation = deliverable.participation
    if participation.profile.user_id != user.pk:
        raise PermissionDenied("Only the creator submits deliverables.")
    if participation.status != P.ACCEPTED:
        raise Conflict("This collaboration isn't active.", code="not_accepted")
    if deliverable.status == DeliverableStatus.APPROVED:
        raise Conflict("Already approved.", code="already_approved")
    url = (url or "").strip()
    if not url.lower().startswith("https://"):
        raise ValidationError(details={"url": ["Link to the published content (https://)."]})
    if campaign.disclosure_required and not disclosure_confirmed:
        raise ValidationError(
            "Confirm the content is labelled as sponsored (#ad).",
            code="disclosure_required",
            details={"disclosure_confirmed": ["Required for this campaign."]},
        )
    deliverable.submission_url = url[:500]
    deliverable.submission_note = (note or "")[:2000]
    deliverable.disclosure_confirmed = bool(disclosure_confirmed)
    deliverable.status = DeliverableStatus.SUBMITTED
    deliverable.submitted_at = timezone.now()
    deliverable.save()
    publish(
        events.DELIVERABLE_SUBMITTED,
        {"deliverable_id": deliverable.pk, **_payload(participation)},
        actor=user,
    )
    return deliverable


@transaction.atomic
def review_deliverable(*, actor: Any, deliverable_id: Any, approve: bool, note: str = "") -> Deliverable:
    _, deliverable, is_brand = _deliverable(actor, deliverable_id)
    if not is_brand:
        raise PermissionDenied("Only the brand reviews deliverables.")
    if deliverable.status != DeliverableStatus.SUBMITTED:
        raise Conflict("Only submitted deliverables can be reviewed.", code="not_submitted")
    if not approve and not (note or "").strip():
        raise ValidationError(details={"note": ["Say what needs to change."]})
    deliverable.status = DeliverableStatus.APPROVED if approve else DeliverableStatus.CHANGES_REQUESTED
    deliverable.review_note = (note or "")[:1000]
    deliverable.reviewed_at = timezone.now()
    deliverable.save()
    publish(
        events.DELIVERABLE_REVIEWED,
        {"deliverable_id": deliverable.pk, "approved": approve, **_payload(deliverable.participation)},
        actor=actor,
    )
    return deliverable
