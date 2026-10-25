"""Hosting: events, organizers, ticket types, schedules, venues and covers.

Every mutation authorises with ``events.manage`` at the event's scope, which
organizers hold implicitly and which host-scope managers (e.g. an
institution's events office) inherit through the scope hierarchy.
"""

from __future__ import annotations

import secrets
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.utils.text import slugify

from university.audit.services import record as audit
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.ids import is_valid_uuid
from university.core.ratelimit import rate_limit
from university.core.uploads import FileUploadValidator
from university.events import events
from university.events.conf import events_settings
from university.events.constants import (
    CONTENT_TYPE,
    ORGANIZER_RANK,
    EventFormat,
    EventStatus,
    EventVisibility,
    NoticeKind,
    OrganizerRole,
)
from university.events.models import Event, EventOrganizer, EventSession, TicketType, Venue
from university.events.selectors import event_scope, get_event
from university.events.services.common import (
    check_window,
    clean_speakers,
    https_url,
    in_future,
    screen,
    valid_timezone,
)
from university.permissions.scopes import Scope
from university.permissions.services import authorize, has_permission

EDITABLE = (
    "title",
    "summary",
    "description",
    "category",
    "format",
    "visibility",
    "venue",
    "location_details",
    "online_url",
    "timezone",
    "starts_at",
    "ends_at",
    "registration_opens_at",
    "registration_closes_at",
    "capacity",
    "waitlist_enabled",
    "requires_approval",
)
#: Changes that attendees must hear about.
RESCHEDULE_FIELDS = frozenset({"starts_at", "ends_at", "venue", "format", "location_details"})


def _audit(action: str, actor: Any, target: Any, **metadata: Any) -> None:
    audit(f"events.{action}", actor=actor, target=target, category="events", metadata=metadata)


def _manage(actor: Any, event: Event) -> None:
    authorize(actor, "events.manage", event_scope(event), audit_denial=True)


def _locked(event_id: Any) -> Event:
    event = get_event(event_id)
    return Event.objects.select_for_update().select_related("venue").get(pk=event.pk)


def _unique_slug(title: str) -> str:
    base = slugify(title)[:80] or "event"
    return f"{base}-{secrets.token_hex(3)}"


def _validate(event: Event) -> None:
    """Cross-field rules for an event's current (unsaved) state."""
    if event.category not in events_settings.get("CATEGORIES", []):
        raise ValidationError(details={"category": ["Unknown category."]})
    valid_timezone(event.timezone)
    check_window(event.starts_at, event.ends_at, max_days=int(events_settings.get("MAX_DURATION_DAYS", 30)))
    if event.registration_opens_at and event.registration_closes_at:
        check_window(event.registration_opens_at, event.registration_closes_at, field="registration_closes_at")
    if event.registration_closes_at and event.registration_closes_at > event.ends_at:
        raise ValidationError(details={"registration_closes_at": ["Must be before the event ends."]})
    event.online_url = https_url(event.online_url, "online_url")
    if event.visibility == EventVisibility.AUDIENCE and not event.scope_type:
        raise ValidationError(details={"visibility": ["Only hosted events can be limited to members."]})
    if event.capacity is not None:
        if event.capacity < 1:
            raise ValidationError(details={"capacity": ["Must be at least 1, or empty for unlimited."]})
        if event.capacity < event.seats_taken:
            raise ValidationError(
                details={"capacity": [f"{event.seats_taken} seats are already taken."]}, code="capacity_below_taken"
            )


def _check_publishable(event: Event) -> None:
    in_future(event.starts_at, "starts_at")
    if event.format in (EventFormat.IN_PERSON, EventFormat.HYBRID) and not (event.venue_id or event.location_details):
        raise ValidationError(details={"venue": ["In-person events need a venue or location details."]})
    if event.format in (EventFormat.ONLINE, EventFormat.HYBRID) and not event.online_url:
        raise ValidationError(details={"online_url": ["Online events need a link."]})


def _venue(venue_id: Any) -> Venue | None:
    if not venue_id:
        return None
    venue = Venue.objects.filter(pk=venue_id).first() if is_valid_uuid(venue_id) else None
    if venue is None:
        raise ValidationError(details={"venue": ["Venue not found."]})
    return venue


def _known_scope_type(scope_type: str) -> None:
    from university.core.registry import registry

    if scope_type not in registry.scope_types:
        raise ValidationError(details={"scope_type": ["Unknown host type."]})


# ------------------------------------------------------------------ events
@transaction.atomic
def create_event(*, creator: Any, data: Mapping[str, Any], scope_type: str = "", scope_id: Any = "") -> Event:
    rate_limit("events_create", key=str(creator.pk))
    ensure_can_create(creator, CONTENT_TYPE)
    scope_id = str(scope_id or "")
    if scope_type or scope_id:
        if not (scope_type and scope_id):
            raise ValidationError(details={"scope_id": ["Give both the host type and id."]})
        _known_scope_type(scope_type)
        authorize(creator, "events.manage", Scope(scope_type, scope_id), audit_denial=True)
    elif events_settings.get("CREATION_POLICY") == "permission":
        authorize(creator, "events.create", audit_denial=True)
    elif not creator.email_verified_at:
        raise PermissionDenied("Verify your email address to host events.", code="email_not_verified")
    limit = int(events_settings.get("MAX_UPCOMING_EVENTS_PER_USER", 20))
    upcoming = Event.objects.filter(created_by=creator, ends_at__gte=timezone.now()).exclude(
        status=EventStatus.CANCELLED
    )
    if upcoming.count() >= limit:
        raise PermissionDenied(f"You can host up to {limit} upcoming events.", code="event_limit_reached")
    fields = {k: v for k, v in data.items() if k in EDITABLE}
    fields["venue"] = _venue(fields.get("venue"))
    event = Event(
        **fields,
        slug=_unique_slug(fields.get("title", "")),
        scope_type=scope_type,
        scope_id=scope_id,
        created_by=creator,
    )
    _validate(event)
    screen(f"{event.title}\n{event.summary}\n{event.description}", actor=creator)
    event.save()
    EventOrganizer.objects.create(event=event, user=creator, role=OrganizerRole.OWNER)
    _audit("event.created", creator, event)
    publish(events.EVENT_CREATED, {"event_id": event.pk, "scope_type": scope_type, "scope_id": scope_id}, actor=creator)
    return event


@transaction.atomic
def update_event(*, actor: Any, event_id: Any, data: Mapping[str, Any]) -> Event:
    from university.events.services.notices import notify_attendees
    from university.events.services.registrations import promote_waitlist

    event = _locked(event_id)
    _manage(actor, event)
    if event.status == EventStatus.CANCELLED:
        raise Conflict("Cancelled events can't be edited.", code="event_cancelled")
    changed = []
    for key, value in data.items():
        if key not in EDITABLE:
            continue
        if key == "venue":
            value = _venue(value)
            if (value.pk if value else None) == event.venue_id:
                continue
        elif getattr(event, key) == value:
            continue
        setattr(event, key, value)
        changed.append(key)
    if not changed:
        return event
    _validate(event)
    if event.status == EventStatus.PUBLISHED and {"starts_at", "format", "online_url", "venue"} & set(changed):
        _check_publishable(event)
    screen(f"{event.title}\n{event.summary}\n{event.description}", actor=actor)
    rescheduled = event.status == EventStatus.PUBLISHED and bool(RESCHEDULE_FIELDS & set(changed))
    if rescheduled and {"starts_at", "ends_at"} & set(changed):
        event.registrations.update(reminder_sent_at=None)  # Remind again for the new time.
    event.save()
    _audit("event.updated", actor, event, fields=changed)
    publish(events.EVENT_UPDATED, {"event_id": event.pk, "fields": changed}, actor=actor)
    if rescheduled:
        publish(events.EVENT_RESCHEDULED, {"event_id": event.pk, "fields": changed}, actor=actor)
        notify_attendees(event, NoticeKind.RESCHEDULED)
    if "capacity" in changed or "waitlist_enabled" in changed:
        promote_waitlist(event)
    return event


@transaction.atomic
def publish_event(*, actor: Any, event_id: Any) -> Event:
    event = _locked(event_id)
    _manage(actor, event)
    if event.status != EventStatus.DRAFT:
        raise Conflict("Only drafts can be published.", code="not_draft")
    if event.hidden_at:
        raise PermissionDenied("This event was hidden by the moderators.", code="event_hidden")
    _check_publishable(event)
    screen(f"{event.title}\n{event.summary}\n{event.description}", actor=actor)
    event.status = EventStatus.PUBLISHED
    event.published_at = timezone.now()
    event.save(update_fields=["status", "published_at", "updated_at"])
    _audit("event.published", actor, event)
    publish(
        events.EVENT_PUBLISHED,
        {
            "event_id": event.pk,
            "visibility": event.visibility,
            "scope_type": event.scope_type,
            "scope_id": event.scope_id,
        },
        actor=actor,
    )
    return event


def cancel_event_records(event: Event, reason: str) -> None:
    """Cancel and tell attendees (no authorisation; used by moderation too)."""
    from university.events.services.notices import notify_attendees

    was_published = event.status == EventStatus.PUBLISHED
    event.status = EventStatus.CANCELLED
    event.cancelled_at = timezone.now()
    event.cancellation_reason = reason[:500]
    event.save(update_fields=["status", "cancelled_at", "cancellation_reason", "updated_at"])
    publish(events.EVENT_CANCELLED, {"event_id": event.pk})
    from university.events.models import Registration
    from university.events.services.registrations import request_refund

    for registration in Registration.objects.filter(event=event, status="confirmed").exclude(payment_reference=None):
        request_refund(registration, "The event was cancelled")
    if was_published:
        notify_attendees(event, NoticeKind.CANCELLED)


@transaction.atomic
def cancel_event(*, actor: Any, event_id: Any, reason: str = "") -> Event:
    event = _locked(event_id)
    _manage(actor, event)
    if event.status == EventStatus.CANCELLED:
        return event
    cancel_event_records(event, reason)
    _audit("event.cancelled", actor, event, reason=reason[:500])
    return event


@transaction.atomic
def delete_event(*, actor: Any, event_id: Any) -> None:
    event = _locked(event_id)
    _manage(actor, event)
    if event.status != EventStatus.DRAFT or event.registrations.exists():
        raise Conflict("Only drafts without registrations can be deleted; cancel it instead.", code="cancel_instead")
    event.delete()
    _audit("event.deleted", actor, event)


@transaction.atomic
def set_cover(*, actor: Any, event_id: Any, file: Any) -> Event:
    event = _locked(event_id)
    _manage(actor, event)
    validator = FileUploadValidator(
        allowed_mime_types=events_settings.get("COVER_MIME_TYPES"), max_bytes=events_settings.get("COVER_MAX_BYTES")
    )
    try:
        validator(file)
    except DjangoValidationError as exc:
        raise ValidationError(details={"file": exc.messages}) from None
    old = event.cover.name if event.cover else None
    event._upload_file = file  # The stored extension derives from the content, not the client name.
    event.cover.save(file.name, file, save=False)
    event.save(update_fields=["cover", "updated_at"])
    if old:
        transaction.on_commit(lambda: event.cover.storage.delete(old))
    return event


@transaction.atomic
def remove_cover(*, actor: Any, event_id: Any) -> Event:
    event = _locked(event_id)
    _manage(actor, event)
    if event.cover:
        event.cover.delete(save=False)
        event.save(update_fields=["cover", "updated_at"])
    return event


# -------------------------------------------------------------- organizers
def _rank(actor: Any, event: Event) -> int:
    from university.events.selectors import organizer_role

    role = organizer_role(actor, event)
    if role == OrganizerRole.OWNER:
        return ORGANIZER_RANK[OrganizerRole.OWNER]
    # Host-scope managers and platform staff who aren't organizers act like owners.
    if role is None and has_permission(actor, "events.manage", event_scope(event)):
        return ORGANIZER_RANK[OrganizerRole.OWNER]
    return ORGANIZER_RANK.get(role, 0)


@transaction.atomic
def add_organizer(*, actor: Any, event_id: Any, user_id: Any, role: str) -> EventOrganizer:
    from django.contrib.auth import get_user_model

    event = _locked(event_id)
    _manage(actor, event)
    if role not in (OrganizerRole.ORGANIZER, OrganizerRole.CHECKIN):
        raise ValidationError(details={"role": ["Choose organizer or checkin."]})
    if _rank(actor, event) <= ORGANIZER_RANK[role]:
        raise PermissionDenied("You can only add roles below your own.", code="insufficient_rank")
    user = get_user_model().objects.filter(pk=user_id, is_active=True).first()
    if user is None or not hooks.allows(Hook.USER_CAN_INTERACT, actor, user, "invite"):
        raise NotFound("User not found.")
    if event.organizers.count() >= int(events_settings.get("MAX_ORGANIZERS", 20)):
        raise ValidationError("This event has the maximum number of organizers.", code="organizer_limit")
    existing = event.organizers.filter(user=user).first()
    if existing is not None:
        if existing.role == OrganizerRole.OWNER or _rank(actor, event) <= ORGANIZER_RANK[existing.role]:
            raise PermissionDenied("You can't change this person's role.", code="insufficient_rank")
        existing.role = role
        existing.save(update_fields=["role", "updated_at"])
        organizer = existing
    else:
        organizer = EventOrganizer.objects.create(event=event, user=user, role=role, added_by=actor)
    _audit("organizer.added", actor, event, user_id=str(user.pk), role=role)
    return organizer


@transaction.atomic
def remove_organizer(*, actor: Any, event_id: Any, user_id: Any) -> None:
    event = _locked(event_id)
    organizer = event.organizers.filter(user_id=user_id).first()
    if organizer is None:
        raise NotFound("Organizer not found.")
    if organizer.role == OrganizerRole.OWNER:
        raise Conflict("Transfer ownership before the owner leaves.", code="owner_must_transfer")
    if organizer.user_id != actor.pk:  # Leaving is always allowed.
        _manage(actor, event)
        if _rank(actor, event) <= ORGANIZER_RANK[organizer.role]:
            raise PermissionDenied("You can only remove roles below your own.", code="insufficient_rank")
    organizer.delete()
    _audit("organizer.removed", actor, event, user_id=str(user_id))


@transaction.atomic
def transfer_ownership(*, actor: Any, event_id: Any, user_id: Any) -> None:
    event = _locked(event_id)
    _manage(actor, event)
    owner = event.organizers.filter(role=OrganizerRole.OWNER).first()
    if _rank(actor, event) < ORGANIZER_RANK[OrganizerRole.OWNER]:
        raise PermissionDenied("Only the owner can transfer ownership.", code="insufficient_rank")
    target = event.organizers.filter(user_id=user_id).exclude(role=OrganizerRole.OWNER).first()
    if target is None:
        raise ValidationError("The new owner must already be an organizer.", code="not_an_organizer")
    if owner is not None:
        owner.role = OrganizerRole.ORGANIZER
        owner.save(update_fields=["role", "updated_at"])
    target.role = OrganizerRole.OWNER
    target.save(update_fields=["role", "updated_at"])
    _audit("organizer.ownership_transferred", actor, event, user_id=str(user_id))


# ------------------------------------------------------------ ticket types
def _validate_ticket(event: Event, ticket: TicketType) -> None:
    if ticket.price_minor > 0 and not events_settings.get("PAID_TICKETS_ENABLED", False):
        raise ValidationError(
            "Paid tickets aren't enabled on this platform.", code="paid_tickets_disabled", details={"price_minor": []}
        )
    if ticket.currency not in events_settings.get("CURRENCIES", []):
        raise ValidationError(details={"currency": ["Unsupported currency."]})
    if ticket.quantity is not None and ticket.quantity < ticket.sold:
        raise ValidationError(details={"quantity": [f"{ticket.sold} tickets are already sold."]})
    if ticket.sales_start and ticket.sales_end:
        check_window(ticket.sales_start, ticket.sales_end, field="sales_end")
    if ticket.sales_end and ticket.sales_end > event.ends_at:
        raise ValidationError(details={"sales_end": ["Must be before the event ends."]})


TICKET_FIELDS = (
    "name",
    "description",
    "price_minor",
    "currency",
    "quantity",
    "sales_start",
    "sales_end",
    "is_active",
    "position",
)


@transaction.atomic
def create_ticket_type(*, actor: Any, event_id: Any, data: Mapping[str, Any]) -> TicketType:
    event = _locked(event_id)
    _manage(actor, event)
    if event.ticket_types.count() >= int(events_settings.get("MAX_TICKET_TYPES", 10)):
        raise ValidationError("This event has the maximum number of ticket types.", code="ticket_type_limit")
    fields = {k: v for k, v in data.items() if k in TICKET_FIELDS}
    fields.setdefault("currency", events_settings.get("DEFAULT_CURRENCY", "NGN"))
    ticket = TicketType(event=event, **fields)
    _validate_ticket(event, ticket)
    try:
        with transaction.atomic():
            ticket.save()
    except IntegrityError:
        raise Conflict("A ticket type with this name exists.", code="duplicate_ticket_type") from None
    _audit("ticket_type.created", actor, event, ticket_type_id=str(ticket.pk))
    return ticket


@transaction.atomic
def update_ticket_type(*, actor: Any, event_id: Any, ticket_type_id: Any, data: Mapping[str, Any]) -> TicketType:
    from university.events.services.registrations import promote_waitlist

    event = _locked(event_id)
    _manage(actor, event)
    ticket = TicketType.objects.select_for_update().filter(pk=ticket_type_id, event=event).first()
    if ticket is None:
        raise NotFound("Ticket type not found.")
    if (
        ticket.sold
        and ({"price_minor", "currency"} & set(data))
        and (
            data.get("price_minor", ticket.price_minor) != ticket.price_minor
            or data.get("currency", ticket.currency) != ticket.currency
        )
    ):
        raise Conflict("The price can't change once tickets are sold.", code="price_locked")
    for key, value in data.items():
        if key in TICKET_FIELDS:
            setattr(ticket, key, value)
    _validate_ticket(event, ticket)
    try:
        with transaction.atomic():
            ticket.save()
    except IntegrityError:
        raise Conflict("A ticket type with this name exists.", code="duplicate_ticket_type") from None
    promote_waitlist(event)
    return ticket


@transaction.atomic
def delete_ticket_type(*, actor: Any, event_id: Any, ticket_type_id: Any) -> None:
    event = _locked(event_id)
    _manage(actor, event)
    ticket = TicketType.objects.filter(pk=ticket_type_id, event=event).first()
    if ticket is None:
        raise NotFound("Ticket type not found.")
    if ticket.registrations.exists():
        ticket.is_active = False  # Keep history for existing registrations.
        ticket.save(update_fields=["is_active", "updated_at"])
    else:
        ticket.delete()


# ---------------------------------------------------------------- sessions
SESSION_FIELDS = ("title", "description", "starts_at", "ends_at", "location", "speakers")


def _validate_session(event: Event, session: EventSession) -> None:
    check_window(session.starts_at, session.ends_at)
    if session.starts_at < event.starts_at or session.ends_at > event.ends_at:
        raise ValidationError(details={"starts_at": ["Sessions must fall within the event."]})
    session.speakers = clean_speakers(session.speakers or [])


@transaction.atomic
def create_session(*, actor: Any, event_id: Any, data: Mapping[str, Any]) -> EventSession:
    event = _locked(event_id)
    _manage(actor, event)
    if event.sessions.count() >= int(events_settings.get("MAX_SESSIONS", 100)):
        raise ValidationError("This event has the maximum number of sessions.", code="session_limit")
    session = EventSession(event=event, **{k: v for k, v in data.items() if k in SESSION_FIELDS})
    _validate_session(event, session)
    session.save()
    return session


@transaction.atomic
def update_session(*, actor: Any, event_id: Any, session_id: Any, data: Mapping[str, Any]) -> EventSession:
    event = _locked(event_id)
    _manage(actor, event)
    session = EventSession.objects.filter(pk=session_id, event=event).first()
    if session is None:
        raise NotFound("Session not found.")
    for key, value in data.items():
        if key in SESSION_FIELDS:
            setattr(session, key, value)
    _validate_session(event, session)
    session.save()
    return session


@transaction.atomic
def delete_session(*, actor: Any, event_id: Any, session_id: Any) -> None:
    event = _locked(event_id)
    _manage(actor, event)
    if not EventSession.objects.filter(pk=session_id, event=event).delete()[0]:
        raise NotFound("Session not found.")


# ------------------------------------------------------------------ venues
VENUE_FIELDS = (
    "name",
    "address",
    "city",
    "region",
    "country",
    "latitude",
    "longitude",
    "capacity",
    "accessibility_notes",
)


def _can_edit_venue(actor: Any, venue: Venue) -> bool:
    if venue.scope_type:
        return has_permission(actor, "events.manage", Scope(venue.scope_type, venue.scope_id))
    return venue.created_by_id == actor.pk or has_permission(actor, "events.manage")


@transaction.atomic
def create_venue(*, actor: Any, data: Mapping[str, Any], scope_type: str = "", scope_id: Any = "") -> Venue:
    rate_limit("events_venue_create", key=str(actor.pk))
    scope_id = str(scope_id or "")
    if scope_type:
        _known_scope_type(scope_type)
        authorize(actor, "events.manage", Scope(scope_type, scope_id), audit_denial=True)
    elif not actor.email_verified_at:
        raise PermissionDenied("Verify your email address to add venues.", code="email_not_verified")
    venue = Venue(
        **{k: v for k, v in data.items() if k in VENUE_FIELDS},
        scope_type=scope_type,
        scope_id=scope_id,
        created_by=actor,
    )
    venue.country = (venue.country or "").upper()
    screen(f"{venue.name}\n{venue.address}\n{venue.accessibility_notes}", actor=actor)
    venue.save()
    return venue


@transaction.atomic
def update_venue(*, actor: Any, venue_id: Any, data: Mapping[str, Any]) -> Venue:
    venue = Venue.objects.select_for_update().filter(pk=venue_id).first()
    if venue is None:
        raise NotFound("Venue not found.")
    if not _can_edit_venue(actor, venue):
        raise PermissionDenied("You can't edit this venue.")
    for key, value in data.items():
        if key in VENUE_FIELDS:
            setattr(venue, key, value)
    venue.country = (venue.country or "").upper()
    screen(f"{venue.name}\n{venue.address}\n{venue.accessibility_notes}", actor=actor)
    venue.save()
    return venue
