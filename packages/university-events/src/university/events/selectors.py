"""Read-side rules: who can see, manage and check in to events."""

from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from university.core.audiences import is_member, member_scopes
from university.core.exceptions import NotFound
from university.core.ids import is_valid_uuid
from university.events.constants import (
    ACTIVE_STATUSES,
    EVENT_SCOPE,
    EventStatus,
    EventVisibility,
)
from university.events.models import Event, EventOrganizer, Registration, TicketType, Venue
from university.permissions.scopes import Scope
from university.permissions.services import has_permission


def event_scope(event: Event) -> Scope:
    return Scope(EVENT_SCOPE, str(event.pk))


def can_manage(user: Any, event: Event) -> bool:
    """Organizers (implicitly), host-scope event managers and platform staff."""
    return has_permission(user, "events.manage", event_scope(event))


def can_checkin(user: Any, event: Event) -> bool:
    return has_permission(user, "events.checkin", event_scope(event))


def organizer_role(user: Any, event: Event) -> str | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return EventOrganizer.objects.filter(event=event, user=user).values_list("role", flat=True).first()


def registration_for(user: Any, event: Event) -> Registration | None:
    if not getattr(user, "is_authenticated", False):
        return None
    return Registration.objects.filter(event=event, user=user).select_related("ticket_type").first()


def can_view(user: Any, event: Event) -> bool:
    if event.deleted_at is not None:
        return False
    open_status = event.status in (EventStatus.PUBLISHED, EventStatus.CANCELLED)
    if open_status and event.hidden_at is None:
        if event.visibility != EventVisibility.AUDIENCE:
            return True
        if is_member(user, event.scope_type, event.scope_id):
            return True
        # People who registered keep seeing it (e.g. its cancellation) after leaving the audience.
        registration = registration_for(user, event)
        if registration is not None and registration.status in ACTIVE_STATUSES:
            return True
    # Drafts, hidden events and audience events for outsiders: organizers and managers only.
    return can_checkin(user, event) or can_manage(user, event)


def get_event(event_id: Any) -> Event:
    event = Event.objects.select_related("venue").filter(pk=event_id).first() if is_valid_uuid(event_id) else None
    if event is None:
        raise NotFound("Event not found.")
    return event


def get_visible_event(user: Any, event_id: Any) -> Event:
    event = get_event(event_id)
    if not can_view(user, event):
        raise NotFound("Event not found.")
    return event


def get_visible_event_by_slug(user: Any, slug: str) -> Event:
    event = Event.objects.select_related("venue").filter(slug=slug).first()
    if event is None or not can_view(user, event):
        raise NotFound("Event not found.")
    return event


def _audience_filter(user: Any) -> Q:
    scopes = member_scopes(user) if getattr(user, "is_authenticated", False) else frozenset()
    q = Q(visibility=EventVisibility.PUBLIC)
    for scope_type, scope_id in scopes:
        q |= Q(visibility=EventVisibility.AUDIENCE, scope_type=scope_type, scope_id=str(scope_id))
    return q


def _when(value: Any) -> dt.datetime | None:
    if not value:
        return None
    parsed = parse_datetime(str(value))
    if parsed is None:
        try:
            parsed = dt.datetime.combine(dt.date.fromisoformat(str(value)), dt.time.min)
        except ValueError:
            return None
    return parsed if timezone.is_aware(parsed) else timezone.make_aware(parsed, dt.UTC)


def discover(user: Any, params: Mapping[str, Any]) -> QuerySet[Event]:
    """Published, listed events the viewer may see; upcoming first by default."""
    qs = (
        Event.objects.filter(status=EventStatus.PUBLISHED, hidden_at__isnull=True)
        .filter(_audience_filter(user))
        .select_related("venue")
    )
    start, end = _when(params.get("from")), _when(params.get("to"))
    qs = qs.filter(ends_at__gte=start or timezone.now())
    if end:
        qs = qs.filter(starts_at__lte=end)
    if q := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(Q(title__icontains=q) | Q(summary__icontains=q))
    for field in ("category", "format"):
        if value := params.get(field):
            qs = qs.filter(**{field: value})
    if params.get("scope_type") and params.get("scope_id"):
        qs = qs.filter(scope_type=params["scope_type"], scope_id=str(params["scope_id"]))
    if city := params.get("city"):
        qs = qs.filter(venue__city__iexact=city)
    if country := params.get("country"):
        qs = qs.filter(venue__country__iexact=country)
    if str(params.get("free", "")).lower() in ("1", "true", "yes"):
        paid = TicketType.objects.filter(price_minor__gt=0, is_active=True).values("event_id")
        qs = qs.exclude(pk__in=paid)
    return qs.order_by("starts_at", "id")


def organizing(user: Any) -> QuerySet[Event]:
    return Event.objects.filter(organizers__user=user).select_related("venue").order_by("-starts_at")


def my_registrations(user: Any, *, upcoming: bool | None = None) -> QuerySet[Registration]:
    qs = Registration.objects.filter(user=user, event__deleted_at__isnull=True).select_related(
        "event", "event__venue", "ticket_type"
    )
    if upcoming is True:
        qs = qs.filter(event__ends_at__gte=timezone.now())
    elif upcoming is False:
        qs = qs.filter(event__ends_at__lt=timezone.now())
    return qs.order_by("event__starts_at")


def attendees(event: Event, params: Mapping[str, Any]) -> QuerySet[Registration]:
    qs = Registration.objects.filter(event=event).select_related("user", "ticket_type")
    if status := params.get("status"):
        qs = qs.filter(status=status)
    if str(params.get("checked_in", "")).lower() in ("1", "true"):
        qs = qs.filter(checked_in_at__isnull=False)
    return qs.order_by("status", "waitlisted_at", "created_at")


def venues(params: Mapping[str, Any]) -> QuerySet[Venue]:
    qs = Venue.objects.all()
    if q := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(Q(name__icontains=q) | Q(city__icontains=q))
    if params.get("scope_type") and params.get("scope_id"):
        qs = qs.filter(scope_type=params["scope_type"], scope_id=str(params["scope_id"]))
    if country := params.get("country"):
        qs = qs.filter(country__iexact=country)
    return qs.order_by("name")
