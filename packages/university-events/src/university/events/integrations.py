"""Core hook implementations: organizer grants, scope parents, export and purge."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from university.core.ids import is_valid_uuid
from university.events.constants import EVENT_SCOPE, OrganizerRole

#: Permissions each organizer role holds *at its event's scope*.
ROLE_PERMISSIONS: dict[str, list[str]] = {
    OrganizerRole.OWNER: ["events.manage", "events.checkin"],
    OrganizerRole.ORGANIZER: ["events.manage", "events.checkin"],
    OrganizerRole.CHECKIN: ["events.checkin"],
}


def _authenticated(user: Any) -> bool:
    return bool(getattr(user, "is_authenticated", False))


def implicit_grants(user: Any, scope: Any) -> list[str]:
    from university.events.models import EventOrganizer

    if scope.type != EVENT_SCOPE or not _authenticated(user) or not is_valid_uuid(scope.id):
        return []
    role = EventOrganizer.objects.filter(event_id=scope.id, user=user).values_list("role", flat=True).first()
    return list(ROLE_PERMISSIONS.get(role, [])) if role else []


def implicit_scopes(user: Any, code: str) -> list[tuple[str, Any]]:
    from university.events.models import EventOrganizer

    if not _authenticated(user):
        return []
    roles = [role for role, codes in ROLE_PERMISSIONS.items() if code in codes]
    if not roles:
        return []
    ids = EventOrganizer.objects.filter(user=user, role__in=roles).values_list("event_id", flat=True)
    return [(EVENT_SCOPE, event_id) for event_id in ids]


def event_parents(event_id: Any) -> list[tuple[str, Any]]:
    """Hosted events sit under their host scope (institution, community …)."""
    from university.events.models import Event

    if not is_valid_uuid(event_id):
        return []
    row = Event.all_objects.filter(pk=event_id).values_list("scope_type", "scope_id").first()
    return [row] if row and row[0] else []


def export_data(user: Any) -> dict[str, Any]:
    from university.events.models import EventOrganizer, Registration

    return {
        "event_registrations": [
            {
                "event": r.event.title,
                "starts_at": r.event.starts_at.isoformat(),
                "status": r.status,
                "ticket_type": r.ticket_type.name if r.ticket_type else None,
                "amount_minor": r.amount_minor,
                "currency": r.currency,
                "checked_in_at": r.checked_in_at.isoformat() if r.checked_in_at else None,
                "share_contact": r.share_contact,
                "registered_at": r.created_at.isoformat(),
            }
            for r in Registration.objects.filter(user=user).select_related("event", "ticket_type")
        ],
        "events_organized": [
            {"event": o.event.title, "role": o.role, "starts_at": o.event.starts_at.isoformat()}
            for o in EventOrganizer.objects.filter(user=user).select_related("event")
        ],
    }


def purge(user_id: Any) -> None:
    from university.events.constants import SEAT_STATUSES
    from university.events.models import Event, EventOrganizer, Registration, Venue
    from university.events.services.registrations import _adjust, _lock_event, promote_waitlist

    for event_id in set(Registration.objects.filter(user_id=user_id).values_list("event_id", flat=True)):
        with transaction.atomic():
            event = _lock_event(event_id)
            registration = (
                Registration.objects.select_for_update()
                .filter(event=event, user_id=user_id)
                .select_related("ticket_type")
                .first()
            )
            if registration is None:
                continue
            held = registration.status in SEAT_STATUSES
            if held:
                _adjust(event, registration.ticket_type, -1)
            registration.delete()
            if held:
                promote_waitlist(event)
    # Hosted events stay (attendees rely on them); scope managers keep authority.
    EventOrganizer.objects.filter(user_id=user_id).delete()
    Event.all_objects.filter(created_by_id=user_id).update(created_by=None)
    Venue.all_objects.filter(created_by_id=user_id).update(created_by=None)
    Registration.objects.filter(checked_in_by_id=user_id).update(checked_in_by=None)
