"""Events composed with community, social, moderation and notifications."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.community import services as community_services
from university.core.testing import create_user
from university.events import services as event_services
from university.moderation.models import ModerationCase

pytestmark = pytest.mark.django_db

EVENTS = "/api/v1/events/"


def soon(hours: float) -> str:
    return (timezone.now() + dt.timedelta(hours=hours)).isoformat()


def titles(client):
    return [n["title"] for n in client.get("/api/v1/notifications/").json()["results"]]


@pytest.fixture
def ngozi(db):
    return create_user("ngozi@example.com", handle="ngozi")


@pytest.fixture
def club(user):
    return community_services.create_community(creator=user, data={"name": "Robotics", "privacy": "restricted"})


def host_club_event(client, club, **extra):
    payload = {
        "title": "Robot Wars Night",
        "category": "tech",
        "location_details": "Engineering Lab 2",
        "starts_at": soon(48),
        "ends_at": soon(51),
        "host_type": "community",
        "host_id": str(club.pk),
        "visibility": "audience",
        **extra,
    }
    response = client.post(EVENTS, payload, format="json")
    assert response.status_code == 201, response.json()
    event = response.json()
    assert client.post(f"{EVENTS}{event['id']}/publish/").status_code == 200
    return event


def join(client, club, owner_client, user):
    client.post(f"/api/v1/communities/{club.pk}/join/")
    requests = owner_client.get(f"/api/v1/communities/{club.pk}/requests/").json()["results"]
    for req in requests:
        owner_client.post(f"/api/v1/communities/{club.pk}/members/{req['user']['id']}/approve/")


@pytest.mark.security
def test_community_admins_host_members_only_events(auth_client, user, other_user, ngozi, club):
    owner = auth_client(user)
    event = host_club_event(owner, club, capacity=1)
    outsider = auth_client(ngozi)
    assert outsider.get(f"{EVENTS}{event['id']}/").status_code == 404
    assert outsider.post(f"{EVENTS}{event['id']}/register/", {}, format="json").status_code == 404
    # Plain members can't host for the community (events.manage is for owners and admins).
    join(auth_client(other_user), club, owner, other_user)
    member_host = auth_client(other_user).post(
        EVENTS,
        {"title": "x", "starts_at": soon(5), "ends_at": soon(6), "host_type": "community", "host_id": str(club.pk)},
        format="json",
    )
    assert member_host.status_code == 403
    registered = auth_client(other_user).post(f"{EVENTS}{event['id']}/register/", {}, format="json")
    assert registered.json()["status"] == "confirmed"
    assert titles(auth_client(other_user))[0] == "You're registered for Robot Wars Night."


def test_waitlist_cancellation_and_reminder_notifications(auth_client, user, other_user, ngozi):
    host = auth_client(user)
    event = host.post(
        EVENTS,
        {"title": "Career Fair", "location_details": "Hall A", "starts_at": soon(5), "ends_at": soon(8), "capacity": 1},
        format="json",
    ).json()
    host.post(f"{EVENTS}{event['id']}/publish/")
    first, second = auth_client(other_user), auth_client(ngozi)
    first.post(f"{EVENTS}{event['id']}/register/", {}, format="json")
    second.post(f"{EVENTS}{event['id']}/register/", {}, format="json")
    assert titles(second) == ["You're on the waitlist for Career Fair."]
    first.delete(f"{EVENTS}{event['id']}/registration/")
    # One notice for the promotion, not a second "registered" for the same change.
    assert titles(second) == [
        "A spot opened up: you're now registered for Career Fair.",
        "You're on the waitlist for Career Fair.",
    ]
    assert event_services.send_reminders() == 1
    assert titles(second)[0] == "Career Fair starts soon."
    host.post(f"{EVENTS}{event['id']}/cancel/", {"reason": "Storm"}, format="json")
    assert titles(second)[0] == "Career Fair was cancelled."
    assert "Career Fair was cancelled." not in titles(first)  # They had cancelled.


@pytest.mark.security
def test_social_blocks_prevent_registration(auth_client, user, other_user):
    host = auth_client(user)
    event = host.post(
        EVENTS,
        {"title": "Open Mic", "location_details": "Cafe", "starts_at": soon(24), "ends_at": soon(26)},
        format="json",
    ).json()
    host.post(f"{EVENTS}{event['id']}/publish/")
    host.post(f"/api/v1/social/users/{other_user.pk}/block/")
    assert auth_client(other_user).post(f"{EVENTS}{event['id']}/register/", {}, format="json").status_code == 404


@pytest.mark.security
def test_event_reports_go_to_the_host_communitys_moderators(auth_client, user, other_user, ngozi, club):
    owner = auth_client(user)
    event = host_club_event(owner, club, visibility="public")
    # Grace becomes a community moderator; Ngozi reports the event.
    join(auth_client(other_user), club, owner, other_user)
    owner.patch(f"/api/v1/communities/{club.pk}/members/{other_user.pk}/", {"role": "moderator"}, format="json")
    report = auth_client(ngozi).post(
        "/api/v1/moderation/reports/",
        {"content_type": "events.event", "object_id": event["id"], "reason": "spam"},
        format="json",
    )
    assert report.status_code == 201, report.json()
    case = ModerationCase.objects.get()
    assert (case.scope_type, case.scope_id) == ("community", str(club.pk))
    queue = auth_client(other_user).get("/api/v1/moderation/cases/").json()["results"]
    assert [c["id"] for c in queue] == [str(case.pk)]
    hidden = auth_client(other_user).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "Scam"}, format="json"
    )
    assert hidden.status_code == 201, hidden.json()
    assert auth_client(ngozi).get(f"{EVENTS}{event['id']}/").status_code == 404
    assert titles(owner)[0] == "Some of your content was hidden by the moderators."
