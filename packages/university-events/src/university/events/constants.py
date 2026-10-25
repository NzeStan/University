from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

EVENT_SCOPE = "event"
CONTENT_TYPE = "events.event"


class EventStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    PUBLISHED = "published", _("Published")
    CANCELLED = "cancelled", _("Cancelled")


class EventVisibility(models.TextChoices):
    #: Listed in discovery; anyone can see it.
    PUBLIC = "public", _("Public")
    #: Not listed; anyone with the link can see it.
    UNLISTED = "unlisted", _("Unlisted")
    #: Only members of the host scope (e.g. an institution or community).
    AUDIENCE = "audience", _("Members of the host only")


class EventFormat(models.TextChoices):
    IN_PERSON = "in_person", _("In person")
    ONLINE = "online", _("Online")
    HYBRID = "hybrid", _("Hybrid")


class OrganizerRole(models.TextChoices):
    OWNER = "owner", _("Owner")
    ORGANIZER = "organizer", _("Organizer")
    #: Door staff: may check attendees in and see the attendee list.
    CHECKIN = "checkin", _("Check-in staff")


ORGANIZER_RANK = {OrganizerRole.CHECKIN: 1, OrganizerRole.ORGANIZER: 2, OrganizerRole.OWNER: 3}


class RegistrationStatus(models.TextChoices):
    CONFIRMED = "confirmed", _("Confirmed")
    WAITLISTED = "waitlisted", _("Waitlisted")
    PENDING_APPROVAL = "pending_approval", _("Awaiting approval")
    #: Holding a seat while a paid ticket is being paid for.
    PENDING_PAYMENT = "pending_payment", _("Awaiting payment")
    CANCELLED = "cancelled", _("Cancelled")
    DECLINED = "declined", _("Declined")
    #: A payment hold ran out.
    EXPIRED = "expired", _("Expired")


#: Statuses that occupy a seat (and a ticket of their type).
SEAT_STATUSES = frozenset({RegistrationStatus.CONFIRMED, RegistrationStatus.PENDING_PAYMENT})
#: Statuses that count as "registered" (can't register again).
ACTIVE_STATUSES = SEAT_STATUSES | {RegistrationStatus.WAITLISTED, RegistrationStatus.PENDING_APPROVAL}


class NoticeKind(models.TextChoices):
    CANCELLED = "cancelled", _("Event cancelled")
    RESCHEDULED = "rescheduled", _("Event rescheduled")
    REMINDER = "reminder", _("Reminder")
