"""Opportunity mutations. Every service authorises, validates, audits and publishes ids-only events.

Scam protection is layered: posting needs a verified email and passes the spam filter, open postings
are capped per person, "verified employer" is granted only by staff, and anyone can report a
posting (platform moderators may hide, restore or remove it; see ``content.py``).
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.db.models import F
from django.utils import timezone

from university.audit.services import record as audit
from university.core.audiences import is_member
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction
from university.core.tasks import task
from university.core.uploads import FileUploadValidator
from university.opportunities import events
from university.opportunities.conf import opportunities_settings as conf
from university.opportunities.constants import (
    POSTER_DECISIONS,
    ApplicationStatus,
    ApplyMethod,
    OpportunityAudience,
    OpportunityStatus,
    PayPeriod,
)
from university.opportunities.models import Application, Opportunity, SavedOpportunity
from university.opportunities.selectors import can_view
from university.permissions.services import authorize

CONTENT_TYPE = "opportunities.opportunity"
EDITABLE = (
    "kind", "title", "organization_name", "organization_url", "description", "location", "work_mode",
    "pay_min_minor", "pay_max_minor", "currency", "pay_period", "deadline", "starts_on", "apply_method",
    "apply_url", "apply_email", "audience", "scope_id", "tags",
)  # fmt: skip


def _payload(opportunity: Opportunity) -> dict[str, Any]:
    return {"opportunity_id": opportunity.pk, "poster_id": opportunity.poster_id, "kind": opportunity.kind}


def _gate(actor: Any) -> None:
    if conf.get("REQUIRE_VERIFIED_EMAIL", True) and not actor.email_verified_at:
        raise PermissionDenied("Verify your email address to post opportunities.", code="email_not_verified")
    ensure_can_create(actor, CONTENT_TYPE)


def _validate(actor: Any, data: dict[str, Any], current: Opportunity | None = None) -> dict[str, Any]:
    merged = {**({f: getattr(current, f) for f in EDITABLE} if current else {}), **data}
    errors: dict[str, list[str]] = {}
    if len(merged.get("description") or "") > int(conf.get("DESCRIPTION_MAX_LENGTH", 8000)):
        errors["description"] = ["This description is too long."]
    if merged.get("currency") and merged["currency"] not in conf.get("CURRENCIES", []):
        errors["currency"] = ["Unsupported currency."]
    low, high = merged.get("pay_min_minor"), merged.get("pay_max_minor")
    if merged.get("pay_period") == PayPeriod.UNPAID:
        data["pay_min_minor"] = data["pay_max_minor"] = None
    elif low is not None and high is not None and high < low:
        errors["pay_max_minor"] = ["Must be at least the minimum."]
    method = merged.get("apply_method")
    if method == ApplyMethod.EXTERNAL and not merged.get("apply_url"):
        errors["apply_url"] = ["Add the link where people apply."]
    if method == ApplyMethod.EMAIL and not merged.get("apply_email"):
        errors["apply_email"] = ["Add the email address for applications."]
    if merged.get("audience") == OpportunityAudience.INSTITUTION:
        scope_id = merged.get("scope_id")
        if not scope_id:
            errors["scope_id"] = ["Choose the institution."]
        elif not is_member(actor, "institution", scope_id):
            errors["scope_id"] = ["You can only post to institutions you belong to."]
    else:
        data["scope_id"] = ""
    deadline = data.get("deadline")
    if deadline is not None and deadline <= timezone.now():
        errors["deadline"] = ["Choose a time in the future."]
    tags = merged.get("tags") or []
    if not isinstance(tags, list) or len(tags) > 10 or any(not isinstance(t, str) or len(t) > 40 for t in tags):
        errors["tags"] = ["Up to 10 short tags."]
    if errors:
        raise ValidationError(details=errors)
    return data


def _screen(actor: Any, data: dict[str, Any]) -> None:
    text = " ".join(str(data.get(f, "")) for f in ("title", "organization_name", "description"))
    verdict = get_spam_filter().check(text, actor=actor, context={"kind": CONTENT_TYPE})
    if verdict.action in (SpamAction.REJECT, SpamAction.REVIEW):
        raise ValidationError("This posting was flagged by our spam filter.", code="content_rejected")


@transaction.atomic
def create_opportunity(*, actor: Any, data: dict[str, Any], publish_now: bool = False) -> Opportunity:
    _gate(actor)
    data = _validate(actor, {k: v for k, v in data.items() if k in EDITABLE})
    _screen(actor, data)
    opportunity = Opportunity.objects.create(poster=actor, **data)
    audit("opportunities.opportunity.created", actor=actor, target=opportunity)
    if publish_now:
        return set_status(actor=actor, opportunity=opportunity, action="publish")
    return opportunity


def _owned(actor: Any, opportunity: Opportunity) -> None:
    if opportunity.poster_id != actor.pk:
        raise NotFound()


@transaction.atomic
def update_opportunity(*, actor: Any, opportunity: Opportunity, data: dict[str, Any]) -> Opportunity:
    _owned(actor, opportunity)
    data = _validate(actor, {k: v for k, v in data.items() if k in EDITABLE}, opportunity)
    _screen(actor, {**{f: getattr(opportunity, f) for f in EDITABLE}, **data})
    for field, value in data.items():
        setattr(opportunity, field, value)
    opportunity.save()
    audit("opportunities.opportunity.updated", actor=actor, target=opportunity)
    if opportunity.status == OpportunityStatus.OPEN:
        publish(events.OPPORTUNITY_UPDATED, _payload(opportunity), actor=actor)
    return opportunity


@transaction.atomic
def set_status(*, actor: Any, opportunity: Opportunity, action: str) -> Opportunity:
    _owned(actor, opportunity)
    now = timezone.now()
    if action in ("publish", "reopen"):
        _gate(actor)
        if opportunity.is_hidden:
            raise PermissionDenied("This opportunity was hidden by the moderators.", code="hidden")
        if opportunity.deadline and opportunity.deadline <= now:
            raise ValidationError(details={"deadline": ["Move the deadline into the future first."]})
        limit = int(conf.get("MAX_OPEN_PER_USER", 20))
        if (
            Opportunity.objects.filter(poster=actor, status=OpportunityStatus.OPEN).exclude(pk=opportunity.pk).count()
            >= limit
        ):
            raise Conflict(f"You can have up to {limit} open opportunities.", code="open_limit")
        opportunity.status = OpportunityStatus.OPEN
        opportunity.published_at = opportunity.published_at or now
        opportunity.closed_at = None
        opportunity.save(update_fields=["status", "published_at", "closed_at", "updated_at"])
        publish(events.OPPORTUNITY_PUBLISHED, _payload(opportunity), actor=actor)
    elif action == "close":
        opportunity.status = OpportunityStatus.CLOSED
        opportunity.closed_at = now
        opportunity.save(update_fields=["status", "closed_at", "updated_at"])
        publish(events.OPPORTUNITY_CLOSED, _payload(opportunity), actor=actor)
    else:
        raise ValidationError(details={"action": ["Use publish, close or reopen."]})
    audit(f"opportunities.opportunity.{action}", actor=actor, target=opportunity)
    return opportunity


@transaction.atomic
def delete_opportunity(*, actor: Any, opportunity: Opportunity) -> None:
    _owned(actor, opportunity)
    opportunity.delete()
    audit("opportunities.opportunity.deleted", actor=actor, target=opportunity)
    publish(events.OPPORTUNITY_CLOSED, _payload(opportunity), actor=actor)


@transaction.atomic
def verify_poster(*, actor: Any, opportunity: Opportunity, verified: bool) -> Opportunity:
    authorize(actor, "opportunities.verify")
    opportunity.verified_at = timezone.now() if verified else None
    opportunity.verified_by = actor if verified else None
    opportunity.save(update_fields=["verified_at", "verified_by", "updated_at"])
    audit(
        "opportunities.opportunity.verified" if verified else "opportunities.opportunity.unverified",
        actor=actor,
        target=opportunity,
    )
    return opportunity


# ------------------------------------------------------------------ applications
@transaction.atomic
def apply(
    *, applicant: Any, opportunity: Opportunity, cover_note: str = "", contact_email: str = "", resume: Any = None
) -> Application:
    if not can_view(applicant, opportunity) or opportunity.is_hidden:
        raise NotFound()
    if opportunity.poster_id == applicant.pk:
        raise ValidationError("You can't apply to your own opportunity.", code="own_opportunity")
    if opportunity.apply_method != ApplyMethod.IN_APP:
        raise ValidationError("Apply using the organisation's link or email.", code="apply_elsewhere")
    if opportunity.status != OpportunityStatus.OPEN or (
        opportunity.deadline and opportunity.deadline <= timezone.now()
    ):
        raise Conflict("Applications are closed.", code="closed")
    if not hooks.allows(Hook.USER_CAN_INTERACT, applicant, opportunity.poster, "apply"):
        raise NotFound()
    if resume is not None:
        validator = FileUploadValidator(
            allowed_mime_types=conf.get("RESUME_MIME_TYPES"), max_bytes=int(conf.get("RESUME_MAX_BYTES"))
        )
        try:
            validator(resume)
        except DjangoValidationError as exc:
            raise ValidationError(details={"resume": exc.messages}) from None
    try:
        with transaction.atomic():
            application = Application.objects.create(
                opportunity=opportunity,
                applicant=applicant,
                cover_note=(cover_note or "").strip()[:4000],
                contact_email=contact_email or applicant.email,
            )
    except IntegrityError:
        raise Conflict("You've already applied.", code="already_applied") from None
    if resume is not None:
        application._upload_file = resume
        application.resume.save(resume.name, resume, save=True)
    Opportunity.objects.filter(pk=opportunity.pk).update(applications_count=F("applications_count") + 1)
    audit("opportunities.application.submitted", actor=applicant, target=application)
    publish(
        events.APPLICATION_SUBMITTED,
        {
            "application_id": application.pk,
            "opportunity_id": opportunity.pk,
            "applicant_id": applicant.pk,
            "poster_id": opportunity.poster_id,
        },
        actor=applicant,
    )
    return application


def _status_event(application: Application) -> None:
    publish(
        events.APPLICATION_STATUS_CHANGED,
        {
            "application_id": application.pk,
            "opportunity_id": application.opportunity_id,
            "applicant_id": application.applicant_id,
            "status": application.status,
        },
    )


@transaction.atomic
def decide(*, actor: Any, application: Application, status: str) -> Application:
    if application.opportunity.poster_id != actor.pk:
        raise NotFound()
    if status not in POSTER_DECISIONS:
        raise ValidationError(details={"status": ["Choose shortlisted, rejected or hired."]})
    if application.status == ApplicationStatus.WITHDRAWN:
        raise Conflict("The applicant withdrew.", code="withdrawn")
    application.status = status
    application.decided_at = timezone.now()
    application.save(update_fields=["status", "decided_at", "updated_at"])
    audit("opportunities.application.decided", actor=actor, target=application, metadata={"status": status})
    _status_event(application)
    return application


@transaction.atomic
def withdraw(*, applicant: Any, application: Application) -> Application:
    if application.applicant_id != applicant.pk:
        raise NotFound()
    application.status = ApplicationStatus.WITHDRAWN
    application.save(update_fields=["status", "updated_at"])
    if application.resume:
        application.resume.delete(save=True)  # Withdrawn CVs aren't kept.
    audit("opportunities.application.withdrawn", actor=applicant, target=application)
    _status_event(application)
    return application


def save(*, user: Any, opportunity: Opportunity) -> None:
    if not can_view(user, opportunity):
        raise NotFound()
    SavedOpportunity.objects.get_or_create(user=user, opportunity=opportunity)


def unsave(*, user: Any, opportunity: Opportunity) -> None:
    SavedOpportunity.objects.filter(user=user, opportunity=opportunity).delete()


# ------------------------------------------------------------------ housekeeping
@task(name="university.opportunities.close_expired")
def close_expired() -> int:
    """Close open opportunities whose deadline has passed. Safe to run often."""
    if not conf.get("AUTO_CLOSE_AFTER_DEADLINE", True):
        return 0
    now = timezone.now()
    due = list(Opportunity.objects.filter(status=OpportunityStatus.OPEN, deadline__lte=now))
    for opportunity in due:
        Opportunity.objects.filter(pk=opportunity.pk).update(status=OpportunityStatus.CLOSED, closed_at=now)
        publish(events.OPPORTUNITY_CLOSED, _payload(opportunity))
    return len(due)


def retention_cutoff() -> dt.datetime | None:
    days = conf.get("APPLICATION_RETENTION_DAYS")
    return None if days is None else timezone.now() - dt.timedelta(days=int(days))


def purge_old_applications(cutoff: dt.datetime, dry_run: bool) -> int:
    qs = Application.objects.filter(opportunity__closed_at__lt=cutoff)
    if dry_run:
        return qs.count()
    count = 0
    for application in qs.iterator():
        if application.resume:
            application.resume.delete(save=False)
        application.delete()
        count += 1
    return count
