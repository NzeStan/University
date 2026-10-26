"""Registration: seats, waitlists, approval, payment holds and check-in.

Every seat change happens under a row lock on the event, so concurrent
registrations are serialised per event; check constraints back this up in the
database, and a unique constraint makes duplicate registrations impossible.

Payment stays optional and decoupled. A paid ticket holds a seat
(``pending_payment``) and publishes ``events.registration.payment_required``;
a payments module creates a checkout and calls :func:`confirm_payment`.
Unpaid holds expire (:func:`release_expired_holds`) and the seat moves on to
the waitlist.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.hooks import Hook, hooks
from university.core.ratelimit import rate_limit
from university.core.tasks import task
from university.events import events
from university.events.conf import events_settings
from university.events.constants import ACTIVE_STATUSES, SEAT_STATUSES, EventStatus, RegistrationStatus
from university.events.models import Event, Registration, TicketType
from university.events.selectors import event_scope, get_visible_event
from university.events.tickets import lookup_candidates, new_lookup
from university.permissions.services import authorize

S = RegistrationStatus


def _payload(registration: Registration, **extra: Any) -> dict[str, Any]:
    return {
        "registration_id": registration.pk,
        "event_id": registration.event_id,
        "user_id": registration.user_id,
        "status": registration.status,
        **extra,
    }


def _lock_event(event_id: Any) -> Event:
    return Event.objects.select_for_update().get(pk=event_id)


def _seat_available(event: Event, ticket: TicketType | None) -> bool:
    if event.capacity is not None and event.seats_taken >= event.capacity:
        return False
    return ticket is None or ticket.quantity is None or ticket.sold < ticket.quantity


def _adjust(event: Event, ticket: TicketType | None, delta: int) -> None:
    event.seats_taken = max(event.seats_taken + delta, 0)
    event.save(update_fields=["seats_taken", "updated_at"])
    if ticket is not None:
        ticket = TicketType.objects.select_for_update().get(pk=ticket.pk)
        ticket.sold = max(ticket.sold + delta, 0)
        ticket.save(update_fields=["sold", "updated_at"])


def _seat(registration: Registration, event: Event) -> None:
    """Give a registration a seat: confirmed when free, held when paid."""
    ticket = registration.ticket_type
    _adjust(event, ticket, +1)
    now = timezone.now()
    if ticket is not None and not ticket.is_free:
        registration.status = S.PENDING_PAYMENT
        registration.amount_minor = ticket.price_minor
        registration.currency = ticket.currency
        registration.hold_expires_at = now + dt.timedelta(minutes=int(events_settings.get("PAYMENT_HOLD_MINUTES", 15)))
    else:
        registration.status = S.CONFIRMED
        registration.confirmed_at = now
        registration.amount_minor = 0
        registration.currency = ticket.currency if ticket else ""


def _announce(registration: Registration, *, promoted: bool = False) -> None:
    if promoted:
        publish(events.REGISTRATION_PROMOTED, _payload(registration))
    if registration.status == S.CONFIRMED:
        publish(events.REGISTRATION_CONFIRMED, _payload(registration))
    elif registration.status == S.PENDING_PAYMENT:
        publish(
            events.REGISTRATION_PAYMENT_REQUIRED,
            _payload(
                registration,
                ticket_type_id=registration.ticket_type_id,
                amount_minor=registration.amount_minor,
                currency=registration.currency,
                hold_expires_at=registration.hold_expires_at,
            ),
        )
    elif registration.status == S.WAITLISTED:
        publish(events.REGISTRATION_WAITLISTED, _payload(registration))
    elif registration.status == S.PENDING_APPROVAL:
        publish(events.REGISTRATION_PENDING_APPROVAL, _payload(registration))


def _pick_ticket(event: Event, ticket_type_id: Any) -> TicketType | None:
    active = TicketType.objects.select_for_update().filter(event=event, is_active=True)
    if ticket_type_id:
        ticket = active.filter(pk=ticket_type_id).first()
        if ticket is None:
            raise ValidationError(details={"ticket_type": ["Ticket type not available."]})
    else:
        tickets = list(active[:2])
        if not tickets:
            return None  # General admission.
        if len(tickets) > 1:
            raise ValidationError(details={"ticket_type": ["Choose a ticket type."]})
        ticket = tickets[0]
    now = timezone.now()
    if (ticket.sales_start and now < ticket.sales_start) or (ticket.sales_end and now > ticket.sales_end):
        raise ValidationError("This ticket isn't on sale right now.", code="ticket_not_on_sale")
    return ticket


def _check_open(event: Event) -> None:
    now = timezone.now()
    if event.status != EventStatus.PUBLISHED or event.hidden_at is not None:
        raise Conflict("Registration isn't open for this event.", code="registration_closed")
    if event.registration_opens_at and now < event.registration_opens_at:
        raise Conflict("Registration hasn't opened yet.", code="registration_not_open")
    if now >= (event.registration_closes_at or event.starts_at):
        raise Conflict("Registration has closed.", code="registration_closed")


@transaction.atomic
def register(*, user: Any, event_id: Any, ticket_type_id: Any = None, share_contact: bool = False) -> Registration:
    rate_limit("events_register", key=str(user.pk))
    visible = get_visible_event(user, event_id)
    event = _lock_event(visible.pk)
    _check_open(event)
    if event.created_by_id and not hooks.allows(Hook.USER_CAN_INTERACT, user, event.created_by, "register"):
        raise NotFound("Event not found.")  # Blocked: look like nothing is there.
    existing = Registration.objects.select_for_update().filter(event=event, user=user).first()
    if existing is not None and existing.status in ACTIVE_STATUSES:
        return existing  # Idempotent.
    if existing is not None and existing.status == S.DECLINED:
        raise PermissionDenied("The organizers declined your registration.", code="registration_declined")
    ticket = _pick_ticket(event, ticket_type_id)
    registration = existing or Registration(event=event, user=user)
    if not registration.ticket_lookup:
        registration.ticket_lookup = new_lookup(registration.pk)
    registration.ticket_type = ticket
    registration.share_contact = bool(share_contact)
    registration.cancelled_at = registration.hold_expires_at = registration.confirmed_at = None
    registration.waitlisted_at = None
    registration.decision_reason = ""
    if event.requires_approval:
        registration.status = S.PENDING_APPROVAL
    elif _seat_available(event, ticket):
        _seat(registration, event)
    elif event.waitlist_enabled:
        registration.status = S.WAITLISTED
        registration.waitlisted_at = timezone.now()
    else:
        raise Conflict("This event is full.", code="event_full")
    registration.save()
    _announce(registration)
    return registration


def _release(registration: Registration, event: Event) -> None:
    if registration.status in SEAT_STATUSES:
        _adjust(event, registration.ticket_type, -1)


def _end(registration: Registration, event: Event, status: str, *, reason: str = "") -> bool:
    """Move an active registration to a final status, freeing its seat. True if it held one."""
    held = registration.status in SEAT_STATUSES
    _release(registration, event)
    registration.status = status
    registration.cancelled_at = timezone.now()
    registration.hold_expires_at = None
    registration.decision_reason = reason[:255]
    registration.save()
    return held


@transaction.atomic
def cancel_registration(*, user: Any, event_id: Any) -> Registration:
    event = _lock_event(get_visible_event(user, event_id).pk)
    registration = Registration.objects.select_for_update().filter(event=event, user=user).first()
    if registration is None or registration.status not in ACTIVE_STATUSES:
        raise NotFound("You aren't registered for this event.")
    if registration.checked_in_at:
        raise Conflict("You've already checked in.", code="already_checked_in")
    if timezone.now() >= event.ends_at:
        raise Conflict("This event has ended.", code="event_ended")
    was_paid = registration.status == S.CONFIRMED and bool(registration.payment_reference)
    held = _end(registration, event, S.CANCELLED)
    if was_paid and _refund_on_cancel(registration, event):
        request_refund(registration, "Cancelled by the attendee")
    publish(
        events.REGISTRATION_CANCELLED,
        _payload(
            registration, amount_minor=registration.amount_minor, payment_reference=registration.payment_reference
        ),
        actor=user,
    )
    if held:
        promote_waitlist(event)
    return registration


def request_refund(registration: Registration, reason: str) -> None:
    """Ask the payments module (via Core's contract) to refund a paid ticket."""
    from university.core.payables import REFUND_REQUESTED

    if registration.payment_reference and registration.amount_minor:
        publish(REFUND_REQUESTED, {"purpose": "events.registration", "object_id": registration.pk, "reason": reason})


def _refund_on_cancel(registration: Registration, event: Event) -> bool:
    if not events_settings.get("REFUND_ON_ATTENDEE_CANCEL", True):
        return False
    cutoff = event.starts_at - dt.timedelta(hours=int(events_settings.get("REFUND_CUTOFF_HOURS", 24)))
    return timezone.now() <= cutoff


def promote_waitlist(event: Event) -> int:
    """Seat waitlisted people in order while seats are free. Call with the event locked."""
    if not events_settings.get("WAITLIST_AUTO_PROMOTE", True) or event.status != EventStatus.PUBLISHED:
        return 0
    promoted = 0
    queue = (
        Registration.objects.select_for_update(of=("self",))
        .filter(event=event, status=S.WAITLISTED)
        .select_related("ticket_type")
        .order_by("waitlisted_at", "created_at")
    )
    for registration in queue:
        if not _seat_available(event, None):
            break
        if registration.ticket_type_id:
            registration.ticket_type = TicketType.objects.get(pk=registration.ticket_type_id)
            if not registration.ticket_type.is_active or not _seat_available(event, registration.ticket_type):
                continue  # Their ticket type is sold out; others may still fit.
        _seat(registration, event)
        registration.waitlisted_at = None
        registration.save()
        _announce(registration, promoted=True)
        promoted += 1
    return promoted


# --------------------------------------------------------------- organizers
def _organizer_registration(actor: Any, event_id: Any, registration_id: Any) -> tuple[Event, Registration]:
    from university.events.selectors import get_event

    event = _lock_event(get_event(event_id).pk)
    authorize(actor, "events.manage", event_scope(event), audit_denial=True)
    registration = (
        Registration.objects.select_for_update(of=("self",))
        .select_related("ticket_type")
        .filter(pk=registration_id, event=event)
        .first()
    )
    if registration is None:
        raise NotFound("Registration not found.")
    return event, registration


@transaction.atomic
def approve_registration(*, actor: Any, event_id: Any, registration_id: Any) -> Registration:
    event, registration = _organizer_registration(actor, event_id, registration_id)
    if registration.status != S.PENDING_APPROVAL:
        raise Conflict("Only pending registrations can be approved.", code="not_pending")
    if _seat_available(event, registration.ticket_type):
        _seat(registration, event)
    elif event.waitlist_enabled:
        registration.status = S.WAITLISTED
        registration.waitlisted_at = timezone.now()
    else:
        raise Conflict("This event is full.", code="event_full")
    registration.save()
    audit("events.registration.approved", actor=actor, target=registration, category="events")
    _announce(registration)
    return registration


@transaction.atomic
def decline_registration(*, actor: Any, event_id: Any, registration_id: Any, reason: str = "") -> Registration:
    event, registration = _organizer_registration(actor, event_id, registration_id)
    if registration.status not in ACTIVE_STATUSES:
        raise Conflict("This registration isn't active.", code="not_active")
    if registration.checked_in_at:
        raise Conflict("This attendee has already checked in.", code="already_checked_in")
    was_paid = registration.status == S.CONFIRMED and bool(registration.payment_reference)
    held = _end(registration, event, S.DECLINED, reason=reason)
    if was_paid:
        request_refund(registration, "Declined by the organizers")
    audit("events.registration.declined", actor=actor, target=registration, category="events")
    publish(
        events.REGISTRATION_DECLINED,
        _payload(
            registration, amount_minor=registration.amount_minor, payment_reference=registration.payment_reference
        ),
        actor=actor,
    )
    if held:
        promote_waitlist(event)
    return registration


# ----------------------------------------------------------------- payments
@transaction.atomic
def confirm_payment(*, registration_id: Any, reference: str, amount_minor: int, currency: str) -> Registration:
    """Called by a payments module once a held ticket is paid. Idempotent per reference."""
    found = Registration.objects.filter(pk=registration_id).first()
    if found is None:
        raise NotFound("Registration not found.")
    _lock_event(found.event_id)
    registration = Registration.objects.select_for_update().get(pk=found.pk)
    if registration.payment_reference == reference and registration.status == S.CONFIRMED:
        return registration
    if registration.status != S.PENDING_PAYMENT:
        # The hold expired or was cancelled: the payments module should refund.
        raise Conflict("This ticket is no longer held.", code="payment_too_late")
    if int(amount_minor) != registration.amount_minor or currency != registration.currency:
        raise ValidationError("The payment doesn't match the ticket price.", code="payment_mismatch")
    registration.status = S.CONFIRMED
    registration.payment_reference = reference[:128]
    registration.confirmed_at = timezone.now()
    registration.hold_expires_at = None
    registration.save()
    publish(events.REGISTRATION_CONFIRMED, _payload(registration, payment_reference=registration.payment_reference))
    return registration


@task(name="university.events.release_expired_holds")
def release_expired_holds() -> int:
    """Expire unpaid holds and pass their seats to the waitlist."""
    released = 0
    expired = Registration.objects.filter(status=S.PENDING_PAYMENT, hold_expires_at__lt=timezone.now())
    for event_id in set(expired.values_list("event_id", flat=True)):
        with transaction.atomic():
            event = _lock_event(event_id)
            rows = (
                Registration.objects.select_for_update(of=("self",))
                .filter(event=event, status=S.PENDING_PAYMENT, hold_expires_at__lt=timezone.now())
                .select_related("ticket_type")
            )
            freed = 0
            for registration in rows:
                _end(registration, event, S.EXPIRED)
                publish(events.REGISTRATION_EXPIRED, _payload(registration))
                freed += 1
            if freed:
                promote_waitlist(event)
            released += freed
    return released


# ----------------------------------------------------------------- check-in
@transaction.atomic
def check_in(*, actor: Any, event_id: Any, code: str) -> Registration:
    from university.events.selectors import get_event

    event = get_event(event_id)
    authorize(actor, "events.checkin", event_scope(event), audit_denial=True)
    rate_limit("events_checkin", key=str(actor.pk))
    if event.status == EventStatus.CANCELLED:
        raise Conflict("This event was cancelled.", code="event_cancelled")
    registration = (
        Registration.objects.select_for_update(of=("self",))
        .select_related("user", "ticket_type")
        .filter(event=event, ticket_lookup__in=lookup_candidates(code))
        .first()
    )
    if registration is None:
        raise NotFound("Ticket not found.")
    if registration.status != S.CONFIRMED:
        raise Conflict("This ticket isn't valid.", code="ticket_not_valid", details={"status": registration.status})
    if registration.checked_in_at:
        raise Conflict(
            "Already checked in.",
            code="already_checked_in",
            details={"checked_in_at": registration.checked_in_at.isoformat()},
        )
    registration.checked_in_at = timezone.now()
    registration.checked_in_by = actor
    registration.save(update_fields=["checked_in_at", "checked_in_by", "updated_at"])
    audit("events.attendee.checked_in", actor=actor, target=registration, category="events")
    publish(events.ATTENDEE_CHECKED_IN, _payload(registration), actor=actor)
    return registration
