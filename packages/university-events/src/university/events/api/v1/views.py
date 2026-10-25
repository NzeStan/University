from __future__ import annotations

import csv
import io
from collections.abc import Iterable
from typing import Any

from django.http import HttpResponse
from rest_framework import permissions, status
from rest_framework.parsers import FormParser, MultiPartParser
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from university.core.api.pagination import PageNumberPagination
from university.core.api.schema import OpenApiParameter, OpenApiTypes, extend_schema
from university.core.exceptions import AuthenticationFailed, NotFound, PermissionDenied
from university.events import selectors, services
from university.events.api.v1 import serializers as s
from university.events.calendar import build_ics
from university.events.constants import OrganizerRole, RegistrationStatus
from university.events.models import EventOrganizer, Registration, TicketType


def _user(request: Request) -> Any:
    if not request.user.is_authenticated:
        raise AuthenticationFailed()
    return request.user


def _list_context(request: Request, events: Iterable[Any]) -> dict[str, Any]:
    events = list(events)
    ids = [e.pk for e in events]
    context: dict[str, Any] = {
        "request": request,
        "paid_event_ids": set(
            TicketType.objects.filter(event_id__in=ids, is_active=True, price_minor__gt=0).values_list(
                "event_id", flat=True
            )
        ),
    }
    if request.user.is_authenticated and ids:
        context["registrations"] = {
            r.event_id: r for r in Registration.objects.filter(user=request.user, event_id__in=ids)
        }
        context["roles"] = dict(
            EventOrganizer.objects.filter(user=request.user, event_id__in=ids).values_list("event_id", "role")
        )
    return context


def _detail(request: Request, event: Any) -> dict[str, Any]:
    context = _list_context(request, [event])
    context["can_manage"] = selectors.can_manage(request.user, event)
    return s.EventsEventSerializer(event, context=context).data


def _paginate(view: APIView, request: Request, qs: Any, serializer: Any, context_fn: Any = None) -> Response:
    paginator = PageNumberPagination()
    page = paginator.paginate_queryset(qs, request, view=view)
    context = context_fn(request, page) if context_fn else {"request": request}
    return paginator.get_paginated_response(serializer(page, many=True, context=context).data)


def _manageable(request: Request, event_id: Any) -> Any:
    event = selectors.get_visible_event(request.user, event_id)
    if not selectors.can_manage(request.user, event):
        raise PermissionDenied()
    return event


def _staff_view(request: Request, event_id: Any) -> Any:
    """Organizers, check-in staff and managers."""
    event = selectors.get_visible_event(request.user, event_id)
    if not (selectors.can_checkin(request.user, event) or selectors.can_manage(request.user, event)):
        raise PermissionDenied()
    return event


DISCOVERY_PARAMS = ("q", "category", "format", "from", "to", "scope_type", "scope_id", "city", "country", "free")


# ------------------------------------------------------------------ events
class EventListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in DISCOVERY_PARAMS],
        responses=s.EventsEventListSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        qs = selectors.discover(request.user, request.query_params)
        return _paginate(self, request, qs, s.EventsEventListSerializer, _list_context)

    @extend_schema(request=s.EventsEventWriteSerializer, responses={201: s.EventsEventSerializer})
    def post(self, request: Request) -> Response:
        user = _user(request)
        serializer = s.EventsEventWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        host_type, host_id = data.pop("host_type"), data.pop("host_id")
        event = services.create_event(creator=user, data=data, scope_type=host_type, scope_id=host_id)
        return Response(_detail(request, event), status=status.HTTP_201_CREATED)


class EventBySlugView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.EventsEventSerializer)
    def get(self, request: Request, slug: str) -> Response:
        return Response(_detail(request, selectors.get_visible_event_by_slug(request.user, slug)))


class EventDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.EventsEventSerializer)
    def get(self, request: Request, event_id: Any) -> Response:
        return Response(_detail(request, selectors.get_visible_event(request.user, event_id)))

    @extend_schema(request=s.EventsEventWriteSerializer, responses=s.EventsEventSerializer)
    def patch(self, request: Request, event_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_event(user, event_id)
        serializer = s.EventsEventWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = {k: v for k, v in serializer.validated_data.items() if k not in ("host_type", "host_id")}
        return Response(_detail(request, services.update_event(actor=user, event_id=event_id, data=data)))

    @extend_schema(responses={204: None})
    def delete(self, request: Request, event_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_event(user, event_id)
        services.delete_event(actor=user, event_id=event_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class EventPublishView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=None, responses=s.EventsEventSerializer)
    def post(self, request: Request, event_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        return Response(_detail(request, services.publish_event(actor=request.user, event_id=event_id)))


class EventCancelView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.EventsReasonSerializer, responses=s.EventsEventSerializer)
    def post(self, request: Request, event_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        serializer = s.EventsReasonSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = services.cancel_event(actor=request.user, event_id=event_id, reason=serializer.validated_data["reason"])
        return Response(_detail(request, event))


class EventCoverView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser]

    @extend_schema(request=s.EventsCoverSerializer, responses=s.EventsEventSerializer)
    def post(self, request: Request, event_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        serializer = s.EventsCoverSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        event = services.set_cover(actor=request.user, event_id=event_id, file=serializer.validated_data["file"])
        return Response(_detail(request, event))

    @extend_schema(responses=s.EventsEventSerializer)
    def delete(self, request: Request, event_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        return Response(_detail(request, services.remove_cover(actor=request.user, event_id=event_id)))


class EventCalendarView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses={(200, "text/calendar"): OpenApiTypes.STR})
    def get(self, request: Request, event_id: Any) -> HttpResponse:
        event = selectors.get_visible_event(request.user, event_id)
        registration = selectors.registration_for(request.user, event)
        include_link = selectors.can_manage(request.user, event) or (
            registration is not None and registration.status == RegistrationStatus.CONFIRMED
        )
        response = HttpResponse(
            build_ics(event, include_online_url=include_link), content_type="text/calendar; charset=utf-8"
        )
        response["Content-Disposition"] = f'attachment; filename="{event.slug}.ics"'
        response["Cache-Control"] = "private, no-store"
        return response


# ------------------------------------------------------------ ticket types
class TicketTypeListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.EventsTicketTypeSerializer(many=True))
    def get(self, request: Request, event_id: Any) -> Response:
        event = selectors.get_visible_event(request.user, event_id)
        qs = event.ticket_types.all()
        if not selectors.can_manage(request.user, event):
            qs = qs.filter(is_active=True)
        return Response(s.EventsTicketTypeSerializer(qs, many=True).data)

    @extend_schema(request=s.EventsTicketTypeWriteSerializer, responses={201: s.EventsTicketTypeSerializer})
    def post(self, request: Request, event_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_event(user, event_id)
        serializer = s.EventsTicketTypeWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        ticket = services.create_ticket_type(actor=user, event_id=event_id, data=serializer.validated_data)
        return Response(s.EventsTicketTypeSerializer(ticket).data, status=status.HTTP_201_CREATED)


class TicketTypeDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.EventsTicketTypeWriteSerializer, responses=s.EventsTicketTypeSerializer)
    def patch(self, request: Request, event_id: Any, ticket_type_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        serializer = s.EventsTicketTypeWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        ticket = services.update_ticket_type(
            actor=request.user, event_id=event_id, ticket_type_id=ticket_type_id, data=serializer.validated_data
        )
        return Response(s.EventsTicketTypeSerializer(ticket).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, event_id: Any, ticket_type_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        services.delete_ticket_type(actor=request.user, event_id=event_id, ticket_type_id=ticket_type_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# ---------------------------------------------------------------- sessions
class SessionListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.EventsSessionSerializer(many=True))
    def get(self, request: Request, event_id: Any) -> Response:
        event = selectors.get_visible_event(request.user, event_id)
        return Response(s.EventsSessionSerializer(event.sessions.all(), many=True).data)

    @extend_schema(request=s.EventsSessionWriteSerializer, responses={201: s.EventsSessionSerializer})
    def post(self, request: Request, event_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_event(user, event_id)
        serializer = s.EventsSessionWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        session = services.create_session(actor=user, event_id=event_id, data=serializer.validated_data)
        return Response(s.EventsSessionSerializer(session).data, status=status.HTTP_201_CREATED)


class SessionDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.EventsSessionWriteSerializer, responses=s.EventsSessionSerializer)
    def patch(self, request: Request, event_id: Any, session_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        serializer = s.EventsSessionWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        session = services.update_session(
            actor=request.user, event_id=event_id, session_id=session_id, data=serializer.validated_data
        )
        return Response(s.EventsSessionSerializer(session).data)

    @extend_schema(responses={204: None})
    def delete(self, request: Request, event_id: Any, session_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        services.delete_session(actor=request.user, event_id=event_id, session_id=session_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


# -------------------------------------------------------------- organizers
class OrganizerListView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.EventsOrganizerSerializer(many=True))
    def get(self, request: Request, event_id: Any) -> Response:
        event = selectors.get_visible_event(request.user, event_id)
        qs = event.organizers.select_related("user").order_by("-role", "created_at")
        if not selectors.can_manage(request.user, event):
            qs = qs.exclude(role=OrganizerRole.CHECKIN)  # Door staff aren't public.
        return Response(s.EventsOrganizerSerializer(qs, many=True).data)

    @extend_schema(request=s.EventsOrganizerWriteSerializer, responses={201: s.EventsOrganizerSerializer})
    def post(self, request: Request, event_id: Any) -> Response:
        user = _user(request)
        selectors.get_visible_event(user, event_id)
        serializer = s.EventsOrganizerWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        organizer = services.add_organizer(actor=user, event_id=event_id, **serializer.validated_data)
        return Response(s.EventsOrganizerSerializer(organizer).data, status=status.HTTP_201_CREATED)


class OrganizerDetailView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={204: None})
    def delete(self, request: Request, event_id: Any, user_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        services.remove_organizer(actor=request.user, event_id=event_id, user_id=user_id)
        return Response(status=status.HTTP_204_NO_CONTENT)


class TransferOwnershipView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.EventsUserRefSerializer, responses={204: None})
    def post(self, request: Request, event_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        serializer = s.EventsUserRefSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        services.transfer_ownership(actor=request.user, event_id=event_id, user_id=serializer.validated_data["user_id"])
        return Response(status=status.HTTP_204_NO_CONTENT)


# ------------------------------------------------------------ registrations
class RegisterView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.EventsRegisterSerializer, responses={201: s.EventsMyRegistrationSerializer})
    def post(self, request: Request, event_id: Any) -> Response:
        serializer = s.EventsRegisterSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        registration = services.register(
            user=request.user,
            event_id=event_id,
            ticket_type_id=serializer.validated_data.get("ticket_type"),
            share_contact=serializer.validated_data["share_contact"],
        )
        return Response(
            s.EventsMyRegistrationSerializer(registration, context={"request": request}).data,
            status=status.HTTP_201_CREATED,
        )


class MyEventRegistrationView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.EventsMyRegistrationSerializer)
    def get(self, request: Request, event_id: Any) -> Response:
        event = selectors.get_visible_event(request.user, event_id)
        registration = selectors.registration_for(request.user, event)
        if registration is None:
            raise NotFound("You aren't registered for this event.")
        return Response(s.EventsMyRegistrationSerializer(registration, context={"request": request}).data)

    @extend_schema(responses=s.EventsMyRegistrationSerializer)
    def delete(self, request: Request, event_id: Any) -> Response:
        registration = services.cancel_registration(user=request.user, event_id=event_id)
        return Response(s.EventsMyRegistrationSerializer(registration, context={"request": request}).data)


class AttendeeListView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("status", str), OpenApiParameter("checked_in", bool)],
        responses=s.EventsAttendeeSerializer(many=True),
    )
    def get(self, request: Request, event_id: Any) -> Response:
        event = _staff_view(request, event_id)
        return _paginate(self, request, selectors.attendees(event, request.query_params), s.EventsAttendeeSerializer)


def _csv_cell(value: Any) -> str:
    """Neutralise spreadsheet formulas (CSV injection)."""
    text = "" if value is None else str(value)
    return f"'{text}" if text[:1] in ("=", "+", "-", "@", "\t", "\r") else text


class AttendeeExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses={(200, "text/csv"): OpenApiTypes.STR})
    def get(self, request: Request, event_id: Any) -> HttpResponse:
        event = _manageable(request, event_id)
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["name", "handle", "email", "status", "ticket", "checked_in_at", "registered_at"])
        for r in selectors.attendees(event, request.query_params).iterator():
            user = r.user
            writer.writerow(
                [
                    _csv_cell(v)
                    for v in (
                        user.display_name if user.is_active else "",
                        user.handle if user.is_active else "",
                        user.email if r.share_contact and user.is_active else "",
                        r.status,
                        r.ticket_type.name if r.ticket_type_id else "",
                        r.checked_in_at.isoformat() if r.checked_in_at else "",
                        r.created_at.isoformat(),
                    )
                ]
            )
        response = HttpResponse(buffer.getvalue(), content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = f'attachment; filename="{event.slug}-attendees.csv"'
        response["Cache-Control"] = "private, no-store"
        return response


class RegistrationDecisionView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    approve = True

    @extend_schema(request=s.EventsReasonSerializer, responses=s.EventsAttendeeSerializer)
    def post(self, request: Request, event_id: Any, registration_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        if self.approve:
            registration = services.approve_registration(
                actor=request.user, event_id=event_id, registration_id=registration_id
            )
        else:
            serializer = s.EventsReasonSerializer(data=request.data)
            serializer.is_valid(raise_exception=True)
            registration = services.decline_registration(
                actor=request.user,
                event_id=event_id,
                registration_id=registration_id,
                reason=serializer.validated_data["reason"],
            )
        return Response(s.EventsAttendeeSerializer(registration).data)


class CheckInView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(request=s.EventsCheckInSerializer, responses=s.EventsCheckInResultSerializer)
    def post(self, request: Request, event_id: Any) -> Response:
        selectors.get_visible_event(request.user, event_id)
        serializer = s.EventsCheckInSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        registration = services.check_in(actor=request.user, event_id=event_id, code=serializer.validated_data["code"])
        return Response(
            {
                "registration_id": registration.pk,
                "attendee": s.person(registration.user),
                "ticket_type": registration.ticket_type.name if registration.ticket_type_id else None,
                "checked_in_at": registration.checked_in_at,
            }
        )


# --------------------------------------------------------------------- me
class MyRegistrationsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(
        parameters=[OpenApiParameter("upcoming", bool)], responses=s.EventsMyRegistrationSerializer(many=True)
    )
    def get(self, request: Request) -> Response:
        raw = request.query_params.get("upcoming")
        upcoming = None if raw in (None, "") else raw.lower() in ("1", "true", "yes")
        qs = selectors.my_registrations(request.user, upcoming=upcoming)
        return _paginate(self, request, qs, s.EventsMyRegistrationSerializer)


class MyOrganizedEventsView(APIView):
    permission_classes = [permissions.IsAuthenticated]

    @extend_schema(responses=s.EventsEventListSerializer(many=True))
    def get(self, request: Request) -> Response:
        return _paginate(self, request, selectors.organizing(request.user), s.EventsEventListSerializer, _list_context)


# ------------------------------------------------------------------ venues
class VenueListCreateView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(
        parameters=[OpenApiParameter(p, str) for p in ("q", "scope_type", "scope_id", "country")],
        responses=s.EventsVenueSerializer(many=True),
    )
    def get(self, request: Request) -> Response:
        return _paginate(self, request, selectors.venues(request.query_params), s.EventsVenueSerializer)

    @extend_schema(request=s.EventsVenueWriteSerializer, responses={201: s.EventsVenueSerializer})
    def post(self, request: Request) -> Response:
        user = _user(request)
        serializer = s.EventsVenueWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = dict(serializer.validated_data)
        scope_type, scope_id = data.pop("scope_type"), data.pop("scope_id")
        venue = services.create_venue(actor=user, data=data, scope_type=scope_type, scope_id=scope_id)
        return Response(s.EventsVenueSerializer(venue).data, status=status.HTTP_201_CREATED)


class VenueDetailView(APIView):
    permission_classes = [permissions.AllowAny]

    @extend_schema(responses=s.EventsVenueSerializer)
    def get(self, request: Request, venue_id: Any) -> Response:
        venue = selectors.venues({}).filter(pk=venue_id).first()
        if venue is None:
            raise NotFound("Venue not found.")
        return Response(s.EventsVenueSerializer(venue).data)

    @extend_schema(request=s.EventsVenueWriteSerializer, responses=s.EventsVenueSerializer)
    def patch(self, request: Request, venue_id: Any) -> Response:
        user = _user(request)
        serializer = s.EventsVenueWriteSerializer(data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        data = {k: v for k, v in serializer.validated_data.items() if k not in ("scope_type", "scope_id")}
        return Response(s.EventsVenueSerializer(services.update_venue(actor=user, venue_id=venue_id, data=data)).data)
