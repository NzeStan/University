"""Paid tickets, sold through Core's payable contract (no payments import).

The payments module resolves ``events.registration`` here, takes the money,
then calls :meth:`RegistrationPayable.on_paid`, which confirms the held seat.
If the hold expired first, ``confirm_payment`` raises ``Conflict`` and the
payments module refunds automatically.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from university.core.exceptions import Conflict, NotFound
from university.core.ids import is_valid_uuid
from university.core.payables import Payable, PayableAdapter
from university.events.constants import RegistrationStatus
from university.events.models import Registration

PURPOSE = "events.registration"


class RegistrationPayable(PayableAdapter):
    purpose = PURPOSE
    label = "Event ticket"

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        registration = (
            Registration.objects.select_related("event", "ticket_type").filter(pk=object_id).first()
            if is_valid_uuid(object_id)
            else None
        )
        if registration is None or registration.user_id != payer.pk:
            raise NotFound("Registration not found.")
        if registration.status != RegistrationStatus.PENDING_PAYMENT:
            raise Conflict("This ticket isn't awaiting payment.", code="not_awaiting_payment")
        ticket_name = registration.ticket_type.name if registration.ticket_type else "Ticket"
        return Payable(
            purpose=PURPOSE,
            object_id=str(registration.pk),
            payer_id=str(payer.pk),
            amount_minor=registration.amount_minor,
            currency=registration.currency,
            description=f"{registration.event.title} - {ticket_name}"[:200],
            expires_at=registration.hold_expires_at,
            metadata={"event_id": str(registration.event_id)},
        )

    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        from university.events.services.registrations import confirm_payment

        confirm_payment(registration_id=object_id, reference=reference, amount_minor=amount_minor, currency=currency)

    @transaction.atomic
    def on_refunded(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        """A full refund of a still-valid ticket (e.g. by finance) cancels it and frees the seat."""
        from university.core.events import publish
        from university.events import events
        from university.events.services.registrations import _end, _lock_event, _payload, promote_waitlist

        found = Registration.objects.filter(pk=object_id).first()
        if found is None:
            return
        event = _lock_event(found.event_id)
        registration = Registration.objects.select_for_update().select_related("ticket_type").get(pk=found.pk)
        if registration.status != RegistrationStatus.CONFIRMED or amount_minor < registration.amount_minor:
            return
        _end(registration, event, RegistrationStatus.CANCELLED, reason="Refunded")
        publish(events.REGISTRATION_CANCELLED, _payload(registration, refunded=True))
        promote_waitlist(event)
