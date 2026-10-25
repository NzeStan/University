from __future__ import annotations

from django.urls import path

from university.events.api.v1 import views

app_name = "events"

E = "events/<uuid:event_id>/"

urlpatterns = [
    path("events/", views.EventListCreateView.as_view(), name="event-list"),
    path("events/by-slug/<slug:slug>/", views.EventBySlugView.as_view(), name="event-by-slug"),
    path(E, views.EventDetailView.as_view(), name="event-detail"),
    path(f"{E}publish/", views.EventPublishView.as_view(), name="event-publish"),
    path(f"{E}cancel/", views.EventCancelView.as_view(), name="event-cancel"),
    path(f"{E}cover/", views.EventCoverView.as_view(), name="event-cover"),
    path(f"{E}calendar.ics", views.EventCalendarView.as_view(), name="event-calendar"),
    path(f"{E}ticket-types/", views.TicketTypeListView.as_view(), name="ticket-type-list"),
    path(f"{E}ticket-types/<uuid:ticket_type_id>/", views.TicketTypeDetailView.as_view(), name="ticket-type-detail"),
    path(f"{E}sessions/", views.SessionListView.as_view(), name="session-list"),
    path(f"{E}sessions/<uuid:session_id>/", views.SessionDetailView.as_view(), name="session-detail"),
    path(f"{E}organizers/", views.OrganizerListView.as_view(), name="organizer-list"),
    path(f"{E}organizers/<uuid:user_id>/", views.OrganizerDetailView.as_view(), name="organizer-detail"),
    path(f"{E}transfer-ownership/", views.TransferOwnershipView.as_view(), name="transfer-ownership"),
    path(f"{E}register/", views.RegisterView.as_view(), name="event-register"),
    path(f"{E}registration/", views.MyEventRegistrationView.as_view(), name="my-event-registration"),
    path(f"{E}registrations/", views.AttendeeListView.as_view(), name="attendee-list"),
    path(f"{E}registrations/export.csv", views.AttendeeExportView.as_view(), name="attendee-export"),
    path(
        f"{E}registrations/<uuid:registration_id>/approve/",
        views.RegistrationDecisionView.as_view(),
        name="registration-approve",
    ),
    path(
        f"{E}registrations/<uuid:registration_id>/decline/",
        type("DeclineRegistrationView", (views.RegistrationDecisionView,), {"approve": False}).as_view(),
        name="registration-decline",
    ),
    path(f"{E}check-in/", views.CheckInView.as_view(), name="event-check-in"),
    path("me/event-registrations/", views.MyRegistrationsView.as_view(), name="my-registrations"),
    path("me/events/", views.MyOrganizedEventsView.as_view(), name="my-events"),
    path("venues/", views.VenueListCreateView.as_view(), name="venue-list"),
    path("venues/<uuid:venue_id>/", views.VenueDetailView.as_view(), name="venue-detail"),
]
