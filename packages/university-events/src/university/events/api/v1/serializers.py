from __future__ import annotations

from typing import Any

from django.utils import timezone
from rest_framework import serializers

from university.core.api.schema import extend_schema_field
from university.core.api.serializers import StrictModelSerializer
from university.events.constants import (
    EventFormat,
    EventVisibility,
    OrganizerRole,
    RegistrationStatus,
)
from university.events.models import Event, EventOrganizer, EventSession, Registration, TicketType, Venue
from university.events.tickets import ticket_code
from university.users.refs import person_ref


def _media_url(context: dict[str, Any], field: Any) -> str | None:
    if not field:
        return None
    url = field.url
    request = context.get("request")
    return request.build_absolute_uri(url) if request is not None and url.startswith("/") else url


class EventsScopeRefSerializer(serializers.Serializer):
    type = serializers.CharField()
    id = serializers.CharField()


class EventsPersonSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)


def person(user: Any) -> dict[str, Any] | None:
    if user is None or not user.is_active:
        return None
    return person_ref(user)


# ------------------------------------------------------------------ venues
class EventsVenueSerializer(StrictModelSerializer):
    scope = serializers.SerializerMethodField()

    class Meta:
        model = Venue
        fields = (
            "id",
            "name",
            "address",
            "city",
            "region",
            "country",
            "latitude",
            "longitude",
            "capacity",
            "accessibility_notes",
            "scope",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(EventsScopeRefSerializer(allow_null=True))
    def get_scope(self, obj: Venue) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None


class EventsVenueWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=160)
    address = serializers.CharField(max_length=255, required=False, allow_blank=True)
    city = serializers.CharField(max_length=100, required=False, allow_blank=True)
    region = serializers.CharField(max_length=100, required=False, allow_blank=True)
    country = serializers.RegexField(r"^[A-Za-z]{2}$", required=False, allow_blank=True)
    latitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, min_value=-90, max_value=90, required=False, allow_null=True
    )
    longitude = serializers.DecimalField(
        max_digits=9, decimal_places=6, min_value=-180, max_value=180, required=False, allow_null=True
    )
    capacity = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    accessibility_notes = serializers.CharField(max_length=2000, required=False, allow_blank=True)
    scope_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)
    scope_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="", write_only=True)


# ------------------------------------------------------------- ticketing
class EventsTicketTypeSerializer(StrictModelSerializer):
    is_free = serializers.BooleanField(read_only=True)
    remaining = serializers.SerializerMethodField()
    on_sale = serializers.SerializerMethodField()

    class Meta:
        model = TicketType
        fields = (
            "id",
            "name",
            "description",
            "price_minor",
            "currency",
            "is_free",
            "quantity",
            "remaining",
            "on_sale",
            "sales_start",
            "sales_end",
            "is_active",
            "position",
        )
        read_only_fields = fields

    def get_remaining(self, obj: TicketType) -> int | None:
        return None if obj.quantity is None else max(obj.quantity - obj.sold, 0)

    def get_on_sale(self, obj: TicketType) -> bool:
        now = timezone.now()
        return bool(
            obj.is_active
            and not (obj.sales_start and now < obj.sales_start)
            and not (obj.sales_end and now > obj.sales_end)
        )


class EventsTicketTypeWriteSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    description = serializers.CharField(max_length=300, required=False, allow_blank=True)
    price_minor = serializers.IntegerField(min_value=0, max_value=1_000_000_000, required=False)
    currency = serializers.RegexField(r"^[A-Z]{3}$", required=False)
    quantity = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    sales_start = serializers.DateTimeField(required=False, allow_null=True)
    sales_end = serializers.DateTimeField(required=False, allow_null=True)
    is_active = serializers.BooleanField(required=False)
    position = serializers.IntegerField(min_value=0, max_value=1000, required=False)


class EventsSessionSerializer(StrictModelSerializer):
    class Meta:
        model = EventSession
        fields = ("id", "title", "description", "starts_at", "ends_at", "location", "speakers")
        read_only_fields = fields


class EventsSpeakerSerializer(serializers.Serializer):
    name = serializers.CharField(max_length=100)
    title = serializers.CharField(max_length=100, required=False, allow_blank=True)


class EventsSessionWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    description = serializers.CharField(max_length=5000, required=False, allow_blank=True)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    location = serializers.CharField(max_length=160, required=False, allow_blank=True)
    speakers = EventsSpeakerSerializer(many=True, required=False)


# ------------------------------------------------------------------ events
class EventsViewerSerializer(serializers.Serializer):
    registration_id = serializers.UUIDField(allow_null=True)
    registration_status = serializers.CharField(allow_null=True)
    role = serializers.CharField(allow_null=True)


class EventsEventListSerializer(StrictModelSerializer):
    host = serializers.SerializerMethodField()
    venue = EventsVenueSerializer(read_only=True, allow_null=True)
    cover_url = serializers.SerializerMethodField()
    spots_left = serializers.SerializerMethodField()
    is_free = serializers.SerializerMethodField()
    viewer = serializers.SerializerMethodField()

    class Meta:
        model = Event
        fields = (
            "id",
            "slug",
            "title",
            "summary",
            "category",
            "format",
            "status",
            "visibility",
            "host",
            "venue",
            "timezone",
            "starts_at",
            "ends_at",
            "capacity",
            "spots_left",
            "is_free",
            "cover_url",
            "viewer",
        )
        read_only_fields = fields

    @extend_schema_field(EventsScopeRefSerializer(allow_null=True))
    def get_host(self, obj: Event) -> dict[str, str] | None:
        return {"type": obj.scope_type, "id": obj.scope_id} if obj.scope_type else None

    def get_cover_url(self, obj: Event) -> str | None:
        return _media_url(self.context, obj.cover)

    def get_spots_left(self, obj: Event) -> int | None:
        return None if obj.capacity is None else max(obj.capacity - obj.seats_taken, 0)

    def get_is_free(self, obj: Event) -> bool:
        paid = self.context.get("paid_event_ids")
        if paid is not None:
            return obj.pk not in paid
        return not obj.ticket_types.filter(is_active=True, price_minor__gt=0).exists()

    @extend_schema_field(EventsViewerSerializer)
    def get_viewer(self, obj: Event) -> dict[str, Any]:
        registration = (self.context.get("registrations") or {}).get(obj.pk)
        return {
            "registration_id": registration.pk if registration else None,
            "registration_status": registration.status if registration else None,
            "role": (self.context.get("roles") or {}).get(obj.pk),
        }


class EventsEventSerializer(EventsEventListSerializer):
    online_url = serializers.SerializerMethodField()
    ticket_types = serializers.SerializerMethodField()
    sessions = EventsSessionSerializer(many=True, read_only=True)
    can_manage = serializers.SerializerMethodField()
    is_hidden = serializers.SerializerMethodField()

    class Meta(EventsEventListSerializer.Meta):
        fields = (
            *EventsEventListSerializer.Meta.fields,
            "description",
            "location_details",
            "online_url",
            "registration_opens_at",
            "registration_closes_at",
            "waitlist_enabled",
            "requires_approval",
            "ticket_types",
            "sessions",
            "published_at",
            "cancelled_at",
            "cancellation_reason",
            "is_hidden",
            "can_manage",
            "created_at",
        )
        read_only_fields = fields

    def get_online_url(self, obj: Event) -> str | None:
        """Only confirmed attendees and organizers get the link (no gatecrashing)."""
        if self.context.get("can_manage"):
            return obj.online_url or None
        registration = (self.context.get("registrations") or {}).get(obj.pk)
        if registration is not None and registration.status == RegistrationStatus.CONFIRMED:
            return obj.online_url or None
        return None

    @extend_schema_field(EventsTicketTypeSerializer(many=True))
    def get_ticket_types(self, obj: Event) -> list[dict[str, Any]]:
        qs = obj.ticket_types.all() if self.context.get("can_manage") else obj.ticket_types.filter(is_active=True)
        return EventsTicketTypeSerializer(qs, many=True).data

    def get_can_manage(self, obj: Event) -> bool:
        return bool(self.context.get("can_manage"))

    def get_is_hidden(self, obj: Event) -> bool:
        return obj.hidden_at is not None


class EventsEventWriteSerializer(serializers.Serializer):
    title = serializers.CharField(max_length=160)
    summary = serializers.CharField(max_length=300, required=False, allow_blank=True)
    description = serializers.CharField(max_length=20000, required=False, allow_blank=True)
    category = serializers.CharField(max_length=32, required=False)
    format = serializers.ChoiceField(choices=EventFormat.choices, required=False)
    visibility = serializers.ChoiceField(choices=EventVisibility.choices, required=False)
    venue = serializers.UUIDField(required=False, allow_null=True)
    location_details = serializers.CharField(max_length=255, required=False, allow_blank=True)
    online_url = serializers.URLField(max_length=500, required=False, allow_blank=True)
    timezone = serializers.CharField(max_length=64, required=False)
    starts_at = serializers.DateTimeField()
    ends_at = serializers.DateTimeField()
    registration_opens_at = serializers.DateTimeField(required=False, allow_null=True)
    registration_closes_at = serializers.DateTimeField(required=False, allow_null=True)
    capacity = serializers.IntegerField(min_value=1, required=False, allow_null=True)
    waitlist_enabled = serializers.BooleanField(required=False)
    requires_approval = serializers.BooleanField(required=False)
    host_type = serializers.CharField(max_length=32, required=False, allow_blank=True, default="", write_only=True)
    host_id = serializers.CharField(max_length=64, required=False, allow_blank=True, default="", write_only=True)


class EventsReasonSerializer(serializers.Serializer):
    reason = serializers.CharField(max_length=500, required=False, allow_blank=True, default="")


class EventsCoverSerializer(serializers.Serializer):
    file = serializers.FileField()


# -------------------------------------------------------------- organizers
class EventsOrganizerSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()

    class Meta:
        model = EventOrganizer
        fields = ("user", "role", "created_at")
        read_only_fields = fields

    @extend_schema_field(EventsPersonSerializer(allow_null=True))
    def get_user(self, obj: EventOrganizer) -> dict[str, Any] | None:
        return person(obj.user)


class EventsOrganizerWriteSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()
    role = serializers.ChoiceField(choices=[OrganizerRole.ORGANIZER, OrganizerRole.CHECKIN])


class EventsUserRefSerializer(serializers.Serializer):
    user_id = serializers.UUIDField()


# ------------------------------------------------------------ registrations
class EventsRegisterSerializer(serializers.Serializer):
    ticket_type = serializers.UUIDField(required=False, allow_null=True)
    share_contact = serializers.BooleanField(required=False, default=False)


class EventsTicketRefSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class EventsMyRegistrationSerializer(StrictModelSerializer):
    event = EventsEventListSerializer(read_only=True)
    ticket_type = serializers.SerializerMethodField()
    ticket_code = serializers.SerializerMethodField()
    online_url = serializers.SerializerMethodField()
    waitlist_position = serializers.SerializerMethodField()

    class Meta:
        model = Registration
        fields = (
            "id",
            "event",
            "status",
            "ticket_type",
            "ticket_code",
            "online_url",
            "amount_minor",
            "currency",
            "hold_expires_at",
            "waitlist_position",
            "share_contact",
            "checked_in_at",
            "created_at",
        )
        read_only_fields = fields

    @extend_schema_field(EventsTicketRefSerializer(allow_null=True))
    def get_ticket_type(self, obj: Registration) -> dict[str, Any] | None:
        return {"id": obj.ticket_type_id, "name": obj.ticket_type.name} if obj.ticket_type_id else None

    def get_ticket_code(self, obj: Registration) -> str | None:
        """Shown only while the ticket is valid; render it as a QR code at the door."""
        return ticket_code(obj) if obj.status == RegistrationStatus.CONFIRMED else None

    def get_online_url(self, obj: Registration) -> str | None:
        return (obj.event.online_url or None) if obj.status == RegistrationStatus.CONFIRMED else None

    def get_waitlist_position(self, obj: Registration) -> int | None:
        if obj.status != RegistrationStatus.WAITLISTED or obj.waitlisted_at is None:
            return None
        ahead = Registration.objects.filter(
            event_id=obj.event_id, status=RegistrationStatus.WAITLISTED, waitlisted_at__lt=obj.waitlisted_at
        ).count()
        return ahead + 1


class EventsAttendeeSerializer(StrictModelSerializer):
    user = serializers.SerializerMethodField()
    email = serializers.SerializerMethodField()
    ticket_type = serializers.SerializerMethodField()

    class Meta:
        model = Registration
        fields = ("id", "user", "email", "status", "ticket_type", "waitlisted_at", "checked_in_at", "created_at")
        read_only_fields = fields

    @extend_schema_field(EventsPersonSerializer(allow_null=True))
    def get_user(self, obj: Registration) -> dict[str, Any] | None:
        return person(obj.user)

    def get_email(self, obj: Registration) -> str | None:
        """Only when the attendee chose to share it with the organizers."""
        return obj.user.email if obj.share_contact and obj.user.is_active else None

    @extend_schema_field(EventsTicketRefSerializer(allow_null=True))
    def get_ticket_type(self, obj: Registration) -> dict[str, Any] | None:
        return {"id": obj.ticket_type_id, "name": obj.ticket_type.name} if obj.ticket_type_id else None


class EventsCheckInSerializer(serializers.Serializer):
    code = serializers.CharField(max_length=64)


class EventsCheckInResultSerializer(serializers.Serializer):
    registration_id = serializers.UUIDField()
    attendee = EventsPersonSerializer(allow_null=True)
    ticket_type = serializers.CharField(allow_null=True)
    checked_in_at = serializers.DateTimeField()
