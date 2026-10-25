"""Events data model.

::

    Venue ◄── Event ──┬── EventSession     (schedule)
                      ├── EventOrganizer   (owner / organizer / check-in staff)
                      ├── TicketType       (free, or paid behind a payments module)
                      └── Registration     (one per person; seat, waitlist, ticket)

Capacity is enforced in the database as well as in services: counters are
updated under a row lock on the event, and check constraints make it
impossible to sell more seats or tickets than exist. A unique constraint
prevents duplicate registrations.

An event may be hosted by a scope (``scope_type``/``scope_id``, e.g. an
institution or a community): that scope is its permission parent and, for
``audience`` visibility, its audience.
"""

from __future__ import annotations

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils.translation import gettext_lazy as _

from university.core.models import BaseModel, SoftDeleteModel
from university.core.uploads import uuid_upload_to
from university.events.constants import (
    EventFormat,
    EventStatus,
    EventVisibility,
    OrganizerRole,
    RegistrationStatus,
)

USER = settings.AUTH_USER_MODEL


class Venue(BaseModel, SoftDeleteModel):
    name = models.CharField(max_length=160)
    address = models.CharField(max_length=255, blank=True)
    city = models.CharField(max_length=100, blank=True)
    region = models.CharField(max_length=100, blank=True)
    country = models.CharField(max_length=2, blank=True, help_text=_("ISO 3166-1 alpha-2."))
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    capacity = models.PositiveIntegerField(null=True, blank=True)
    accessibility_notes = models.TextField(blank=True)
    #: Optional owning scope (e.g. an institution's halls).
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    created_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("venue")
        indexes = [
            models.Index(fields=["scope_type", "scope_id"], name="univ_evt_venue_scope"),
            models.Index(fields=["country", "city"], name="univ_evt_venue_place"),
        ]

    def __str__(self) -> str:
        return self.name


class Event(BaseModel, SoftDeleteModel):
    title = models.CharField(max_length=160)
    slug = models.SlugField(max_length=120, unique=True)
    summary = models.CharField(max_length=300, blank=True)
    description = models.TextField(blank=True)
    category = models.CharField(max_length=32, default="other")
    format = models.CharField(max_length=16, choices=EventFormat.choices, default=EventFormat.IN_PERSON)
    status = models.CharField(max_length=16, choices=EventStatus.choices, default=EventStatus.DRAFT)
    visibility = models.CharField(max_length=16, choices=EventVisibility.choices, default=EventVisibility.PUBLIC)
    #: Optional host scope: permission parent and, for "audience" visibility, the audience.
    scope_type = models.CharField(max_length=32, blank=True)
    scope_id = models.CharField(max_length=64, blank=True)
    venue = models.ForeignKey(Venue, null=True, blank=True, on_delete=models.SET_NULL, related_name="events")
    location_details = models.CharField(max_length=255, blank=True, help_text=_("Room, floor, directions."))
    #: Revealed only to confirmed attendees and organizers.
    online_url = models.URLField(max_length=500, blank=True)
    timezone = models.CharField(max_length=64, default="Africa/Lagos")
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    registration_opens_at = models.DateTimeField(null=True, blank=True)
    registration_closes_at = models.DateTimeField(null=True, blank=True)
    #: ``None`` means unlimited.
    capacity = models.PositiveIntegerField(null=True, blank=True)
    seats_taken = models.PositiveIntegerField(default=0)
    waitlist_enabled = models.BooleanField(default=True)
    requires_approval = models.BooleanField(default=False)
    cover = models.FileField(upload_to=uuid_upload_to("events/covers"), max_length=255, blank=True)
    created_by = models.ForeignKey(USER, null=True, on_delete=models.SET_NULL, related_name="+")
    published_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    cancellation_reason = models.CharField(max_length=500, blank=True)
    #: Set by moderation; hidden events are visible to organizers only.
    hidden_at = models.DateTimeField(null=True, blank=True)
    hidden_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("event")
        indexes = [
            models.Index(fields=["status", "visibility", "starts_at"], name="univ_evt_discovery"),
            models.Index(fields=["scope_type", "scope_id", "starts_at"], name="univ_evt_scope"),
            models.Index(fields=["category", "starts_at"], name="univ_evt_category"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="univ_evt_ends_after_start"),
            models.CheckConstraint(
                condition=Q(capacity__isnull=True) | Q(seats_taken__lte=F("capacity")),
                name="univ_evt_within_capacity",
            ),
            models.CheckConstraint(
                condition=(Q(scope_type="") & Q(scope_id="")) | (~Q(scope_type="") & ~Q(scope_id="")),
                name="univ_evt_scope_consistent",
            ),
            models.CheckConstraint(
                condition=~Q(visibility=EventVisibility.AUDIENCE) | ~Q(scope_type=""),
                name="univ_evt_audience_needs_scope",
            ),
        ]

    def __str__(self) -> str:
        return self.title

    @property
    def host_scope(self) -> tuple[str, str] | None:
        return (self.scope_type, self.scope_id) if self.scope_type else None

    @property
    def is_full(self) -> bool:
        return self.capacity is not None and self.seats_taken >= self.capacity


class EventSession(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="sessions")
    title = models.CharField(max_length=160)
    description = models.TextField(blank=True)
    starts_at = models.DateTimeField()
    ends_at = models.DateTimeField()
    location = models.CharField(max_length=160, blank=True)
    #: ``[{"name": ..., "title": ...}]`` — speakers need not have accounts.
    speakers = models.JSONField(default=list, blank=True)

    class Meta:
        verbose_name = _("event session")
        ordering = ("starts_at", "title")
        constraints = [
            models.CheckConstraint(condition=Q(ends_at__gt=F("starts_at")), name="univ_evt_session_ends_after_start")
        ]

    def __str__(self) -> str:
        return self.title


class EventOrganizer(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="organizers")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="organized_events")
    role = models.CharField(max_length=16, choices=OrganizerRole.choices, default=OrganizerRole.ORGANIZER)
    added_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    class Meta:
        verbose_name = _("event organizer")
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="univ_evt_organizer_unique"),
            models.UniqueConstraint(fields=["event"], condition=Q(role=OrganizerRole.OWNER), name="univ_evt_one_owner"),
        ]
        indexes = [models.Index(fields=["user", "role"], name="univ_evt_organizer_user")]

    def __str__(self) -> str:
        return f"{self.user_id} {self.role} of {self.event_id}"


class TicketType(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="ticket_types")
    name = models.CharField(max_length=100)
    description = models.CharField(max_length=300, blank=True)
    #: In minor units (kobo, pesewas, cents). Zero is free.
    price_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, default="NGN")
    #: ``None`` means limited only by the event's capacity.
    quantity = models.PositiveIntegerField(null=True, blank=True)
    sold = models.PositiveIntegerField(default=0)
    sales_start = models.DateTimeField(null=True, blank=True)
    sales_end = models.DateTimeField(null=True, blank=True)
    is_active = models.BooleanField(default=True)
    position = models.PositiveSmallIntegerField(default=0)

    class Meta:
        verbose_name = _("ticket type")
        ordering = ("position", "price_minor", "name")
        constraints = [
            models.CheckConstraint(
                condition=Q(quantity__isnull=True) | Q(sold__lte=F("quantity")), name="univ_evt_ticket_within_quantity"
            ),
            models.UniqueConstraint(fields=["event", "name"], name="univ_evt_ticket_name_unique"),
        ]

    def __str__(self) -> str:
        return f"{self.name} ({self.event_id})"

    @property
    def is_free(self) -> bool:
        return self.price_minor == 0


class Registration(BaseModel):
    event = models.ForeignKey(Event, on_delete=models.CASCADE, related_name="registrations")
    user = models.ForeignKey(USER, on_delete=models.CASCADE, related_name="event_registrations")
    ticket_type = models.ForeignKey(
        TicketType, null=True, blank=True, on_delete=models.PROTECT, related_name="registrations"
    )
    status = models.CharField(max_length=20, choices=RegistrationStatus.choices)
    #: Waitlist order (FIFO).
    waitlisted_at = models.DateTimeField(null=True, blank=True)
    confirmed_at = models.DateTimeField(null=True, blank=True)
    cancelled_at = models.DateTimeField(null=True, blank=True)
    #: Payment hold for paid tickets.
    hold_expires_at = models.DateTimeField(null=True, blank=True)
    payment_reference = models.CharField(max_length=128, null=True, blank=True, unique=True)
    amount_minor = models.PositiveIntegerField(default=0)
    currency = models.CharField(max_length=3, blank=True)
    #: Keyed hash of the ticket code (the code itself is derived, never stored).
    ticket_lookup = models.CharField(max_length=64, unique=True)
    #: The attendee agreed to share their email with organizers.
    share_contact = models.BooleanField(default=False)
    checked_in_at = models.DateTimeField(null=True, blank=True)
    checked_in_by = models.ForeignKey(USER, null=True, blank=True, on_delete=models.SET_NULL, related_name="+")
    reminder_sent_at = models.DateTimeField(null=True, blank=True)
    decision_reason = models.CharField(max_length=255, blank=True)

    class Meta:
        verbose_name = _("registration")
        constraints = [
            models.UniqueConstraint(fields=["event", "user"], name="univ_evt_registration_unique"),
        ]
        indexes = [
            models.Index(fields=["event", "status", "waitlisted_at"], name="univ_evt_reg_queue"),
            models.Index(fields=["user", "status"], name="univ_evt_reg_user"),
            models.Index(fields=["status", "hold_expires_at"], name="univ_evt_reg_holds"),
        ]

    def __str__(self) -> str:
        return f"{self.user_id} → {self.event_id} ({self.status})"

    @property
    def holds_seat(self) -> bool:
        return self.status in (RegistrationStatus.CONFIRMED, RegistrationStatus.PENDING_PAYMENT)
