from __future__ import annotations

from typing import Any

from django.contrib import admin

from university.events.models import Event, EventOrganizer, EventSession, Registration, TicketType, Venue


class OrganizerInline(admin.TabularInline):
    model = EventOrganizer
    extra = 0
    raw_id_fields = ("user", "added_by")
    fields = ("user", "role")


class TicketTypeInline(admin.TabularInline):
    model = TicketType
    extra = 0
    fields = ("name", "price_minor", "currency", "quantity", "sold", "is_active")
    readonly_fields = ("sold",)


class SessionInline(admin.TabularInline):
    model = EventSession
    extra = 0
    fields = ("title", "starts_at", "ends_at", "location")


@admin.register(Event)
class EventAdmin(admin.ModelAdmin):
    list_display = ("title", "status", "visibility", "starts_at", "seats_taken", "capacity", "hidden_at")
    list_filter = ("status", "visibility", "format", "category")
    search_fields = ("title", "slug", "summary")
    raw_id_fields = ("created_by", "venue")
    readonly_fields = ("seats_taken", "published_at", "cancelled_at", "hidden_at", "hidden_reason")
    inlines = (OrganizerInline, TicketTypeInline, SessionInline)

    def get_queryset(self, request: Any) -> Any:
        return Event.all_objects.all()


@admin.register(Registration)
class RegistrationAdmin(admin.ModelAdmin):
    list_display = ("event", "user", "status", "ticket_type", "checked_in_at", "created_at")
    list_filter = ("status",)
    raw_id_fields = ("event", "user", "ticket_type", "checked_in_by")
    # Counters move with registrations: change them through the services, not here.
    readonly_fields = ("status", "ticket_type", "ticket_lookup", "payment_reference", "amount_minor", "currency")

    def has_add_permission(self, request: Any) -> bool:
        return False


@admin.register(Venue)
class VenueAdmin(admin.ModelAdmin):
    list_display = ("name", "city", "country", "capacity", "scope_type")
    search_fields = ("name", "city", "address")
    raw_id_fields = ("created_by",)
