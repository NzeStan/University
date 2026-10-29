from __future__ import annotations

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests.audience.apps import MEMBERS
from university.core.events import event_bus
from university.core.testing import create_user
from university.events import services
from university.events.constants import RegistrationStatus
from university.events.models import Event, Registration
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
BASE = "/api/v1/events"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\xdac\xc8\xd5\xb8\t\x00\x02t\x01o\xfbJ\xd2\xe1\x00\x00\x00\x00IEND\xaeB`\x82"  # A real 1x1 PNG: decodes with or without Pillow.
INST = "11111111-1111-4111-8111-111111111111"


def soon(hours: float) -> str:
    return (timezone.now() + dt.timedelta(hours=hours)).isoformat()


def create(client, **overrides):
    payload = {
        "title": "Lagos Tech Meetup",
        "summary": "Talks and networking",
        "category": "tech",
        "format": "in_person",
        "location_details": "Main Auditorium",
        "starts_at": soon(48),
        "ends_at": soon(51),
        **overrides,
    }
    response = client.post(f"{BASE}/", payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def published(client, **overrides):
    event = create(client, **overrides)
    response = client.post(f"{BASE}/{event['id']}/publish/")
    assert response.status_code == 200, response.json()
    return response.json()


def register(client, event, **data):
    return client.post(f"{BASE}/{event['id']}/register/", data, format="json")


def mine(client, event):
    return client.get(f"{BASE}/{event['id']}/registration/").json()


@pytest.fixture
def captured():
    """Collect bus events published during a test."""
    seen: list = []

    def handler(event):
        seen.append(event)

    event_bus.subscribe("events.*", handler)
    yield seen
    event_bus.unsubscribe("events.*", handler)


def names(captured, name):
    return [e.payload for e in captured if e.name == name]


# ----------------------------------------------------------------- hosting
def test_draft_publish_and_discovery(auth_client, api_client, user, other_user):
    host = auth_client(user)
    event = create(host)
    assert event["status"] == "draft" and event["viewer"]["role"] == "owner" and event["can_manage"] is True
    assert api_client.get(f"{BASE}/{event['id']}/").status_code == 404  # Drafts are private.
    assert api_client.get(f"{BASE}/").json()["results"] == []
    host.post(f"{BASE}/{event['id']}/publish/")
    listed = api_client.get(f"{BASE}/").json()["results"]
    assert [e["title"] for e in listed] == ["Lagos Tech Meetup"] and listed[0]["is_free"] is True
    assert api_client.get(f"{BASE}/by-slug/{event['slug']}/").json()["id"] == event["id"]
    assert api_client.get(f"{BASE}/", {"q": "meetup", "category": "tech"}).json()["count"] == 1
    assert api_client.get(f"{BASE}/", {"category": "sports"}).json()["count"] == 0
    assert api_client.get(f"{BASE}/", {"from": soon(100)}).json()["count"] == 0
    # Only managers can edit.
    other = auth_client(other_user)
    assert other.patch(f"{BASE}/{event['id']}/", {"title": "Mine now"}, format="json").status_code == 403


def test_hosting_rules_and_validation(auth_client, user):
    host = auth_client(user)
    unverified = create_user("new@example.com", handle="newbie", verified=False)
    assert (
        auth_client(unverified)
        .post(f"{BASE}/", {"title": "x", "starts_at": soon(5), "ends_at": soon(6)}, format="json")
        .status_code
        == 403
    )
    base = {"title": "Bad", "starts_at": soon(10), "ends_at": soon(9)}
    assert host.post(f"{BASE}/", base, format="json").status_code == 400
    assert host.post(f"{BASE}/", {**base, "ends_at": soon(11), "category": "nope"}, format="json").status_code == 400
    assert (
        host.post(f"{BASE}/", {**base, "ends_at": soon(11), "timezone": "Mars/Base"}, format="json").status_code == 400
    )
    assert (
        host.post(f"{BASE}/", {**base, "ends_at": soon(11), "visibility": "audience"}, format="json").status_code == 400
    )
    assert host.post(f"{BASE}/", {**base, "ends_at": soon(24 * 40)}, format="json").status_code == 400
    online = create(host, format="online", location_details="")
    assert host.post(f"{BASE}/{online['id']}/publish/").json()["error"]["details"]["online_url"]
    insecure = host.patch(f"{BASE}/{online['id']}/", {"online_url": "http://meet.example.com/x"}, format="json")
    assert insecure.status_code == 400
    host.patch(f"{BASE}/{online['id']}/", {"online_url": "https://meet.example.com/x"}, format="json")
    assert host.post(f"{BASE}/{online['id']}/publish/").status_code == 200
    in_person = create(host, location_details="")
    assert host.post(f"{BASE}/{in_person['id']}/publish/").json()["error"]["details"]["venue"]


@pytest.mark.security
def test_hosted_audience_events(auth_client, api_client, user, other_user, third_user):
    host = auth_client(user)
    payload = {
        "title": "EXU Career Fair",
        "starts_at": soon(48),
        "ends_at": soon(52),
        "category": "career",
        "location_details": "Hall A",
        "host_type": "institution",
        "host_id": INST,
        "visibility": "audience",
    }
    assert host.post(f"{BASE}/", payload, format="json").status_code == 403  # Needs events.manage there.
    assign_role(user=user, role_key="events_manager", scope=Scope("institution", INST))
    event = host.post(f"{BASE}/", payload, format="json").json()
    host.post(f"{BASE}/{event['id']}/publish/")
    assert event["host"] == {"type": "institution", "id": INST}
    assert api_client.get(f"{BASE}/{event['id']}/").status_code == 404
    assert auth_client(other_user).get(f"{BASE}/").json()["count"] == 0
    MEMBERS[str(other_user.pk)] = [("institution", INST)]
    assert auth_client(other_user).get(f"{BASE}/").json()["count"] == 1
    assert register(auth_client(other_user), event).status_code == 201
    # A registrant who leaves the audience still sees the event they signed up for.
    MEMBERS.clear()
    assert auth_client(other_user).get(f"{BASE}/{event['id']}/").status_code == 200
    # Other managers of the host scope manage it through the scope hierarchy.
    assign_role(user=third_user, role_key="events_manager", scope=Scope("institution", INST))
    edited = auth_client(third_user).patch(f"{BASE}/{event['id']}/", {"summary": "Bring your CV"}, format="json")
    assert edited.status_code == 200 and edited.json()["can_manage"] is True


# -------------------------------------------------------- capacity & waits
def test_capacity_waitlist_and_promotion(auth_client, user, other_user, third_user, fourth_user, captured):
    event = published(auth_client(user), capacity=2)
    a, b, c = (auth_client(u) for u in (other_user, third_user, fourth_user))
    assert register(a, event).json()["status"] == "confirmed"
    assert register(b, event).json()["status"] == "confirmed"
    waiting = register(c, event).json()
    assert waiting["status"] == "waitlisted" and waiting["waitlist_position"] == 1 and waiting["ticket_code"] is None
    assert register(c, event).json()["id"] == waiting["id"]  # Idempotent.
    assert auth_client(user).get(f"{BASE}/{event['id']}/").json()["spots_left"] == 0
    assert a.delete(f"{BASE}/{event['id']}/registration/").json()["status"] == "cancelled"
    promoted = mine(c, event)
    assert promoted["status"] == "confirmed" and promoted["ticket_code"]
    assert names(captured, "events.registration.promoted")[0]["user_id"] == str(fourth_user.pk)
    assert Event.objects.get(pk=event["id"]).seats_taken == 2
    # Re-registering after cancelling joins the back of the queue.
    assert register(a, event).json()["status"] == "waitlisted"


def test_full_without_waitlist_and_capacity_floor(auth_client, user, other_user, third_user):
    host = auth_client(user)
    event = published(host, capacity=1, waitlist_enabled=False)
    register(auth_client(other_user), event)
    full = register(auth_client(third_user), event)
    assert full.status_code == 409 and full.json()["error"]["code"] == "event_full"
    lowered = host.patch(f"{BASE}/{event['id']}/", {"capacity": 1}, format="json")
    assert lowered.status_code == 200
    raised = host.patch(f"{BASE}/{event['id']}/", {"capacity": 0}, format="json")
    assert raised.status_code == 400


def test_database_guards_capacity_and_duplicates(user, other_user):
    event = services.create_event(
        creator=user,
        data={
            "title": "Guarded",
            "starts_at": timezone.now() + dt.timedelta(days=2),
            "ends_at": timezone.now() + dt.timedelta(days=2, hours=1),
            "capacity": 1,
        },
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Event.objects.filter(pk=event.pk).update(seats_taken=2)
    Registration.objects.create(event=event, user=other_user, status="confirmed", ticket_lookup="a" * 64)
    with pytest.raises(IntegrityError), transaction.atomic():
        Registration.objects.create(event=event, user=other_user, status="waitlisted", ticket_lookup="b" * 64)


def test_approval_flow(auth_client, user, other_user, third_user):
    host = auth_client(user)
    event = published(host, requires_approval=True, capacity=5)
    pending = register(auth_client(other_user), event).json()
    assert pending["status"] == "pending_approval"
    assert Event.objects.get(pk=event["id"]).seats_taken == 0
    approved = host.post(f"{BASE}/{event['id']}/registrations/{pending['id']}/approve/")
    assert approved.json()["status"] == "confirmed"
    other = register(auth_client(third_user), event).json()
    host.post(f"{BASE}/{event['id']}/registrations/{other['id']}/decline/", {"reason": "Members only"}, format="json")
    again = register(auth_client(third_user), event)
    assert again.status_code == 403 and again.json()["error"]["code"] == "registration_declined"
    assert (
        auth_client(third_user).post(f"{BASE}/{event['id']}/registrations/{pending['id']}/approve/").status_code == 403
    )


def test_registration_window(auth_client, user, other_user):
    event = published(auth_client(user), registration_opens_at=soon(10), registration_closes_at=soon(20))
    early = register(auth_client(other_user), event)
    assert early.status_code == 409 and early.json()["error"]["code"] == "registration_not_open"
    Event.objects.filter(pk=event["id"]).update(
        registration_opens_at=timezone.now() - dt.timedelta(hours=2),
        registration_closes_at=timezone.now() - dt.timedelta(hours=1),
    )
    assert register(auth_client(other_user), event).json()["error"]["code"] == "registration_closed"


# -------------------------------------------------------------- ticketing
def test_ticket_types_and_quantities(auth_client, user, other_user, third_user, fourth_user):
    host = auth_client(user)
    event = published(host)
    url = f"{BASE}/{event['id']}/ticket-types/"
    early = host.post(url, {"name": "Early bird", "quantity": 1}, format="json").json()
    host.post(url, {"name": "Regular"}, format="json")
    assert host.post(url, {"name": "Regular"}, format="json").status_code == 409
    paid = host.post(url, {"name": "VIP", "price_minor": 500000}, format="json")
    assert paid.status_code == 400 and paid.json()["error"]["code"] == "paid_tickets_disabled"
    assert register(auth_client(other_user), event).status_code == 400  # Must choose.
    assert register(auth_client(other_user), event, ticket_type=early["id"]).json()["status"] == "confirmed"
    sold_out = register(auth_client(third_user), event, ticket_type=early["id"]).json()
    assert sold_out["status"] == "waitlisted"
    types = {t["name"]: t for t in auth_client(fourth_user).get(url).json()}
    assert types["Early bird"]["remaining"] == 0 and types["Regular"]["remaining"] is None


def test_paid_tickets_hold_confirm_and_expire(settings, auth_client, user, other_user, third_user, captured):
    settings.UNIVERSITY = {"EVENTS": {"PAID_TICKETS_ENABLED": True}}
    host = auth_client(user)
    event = published(host, capacity=1)
    vip = host.post(f"{BASE}/{event['id']}/ticket-types/", {"name": "VIP", "price_minor": 250000}, format="json").json()
    held = register(auth_client(other_user), event, ticket_type=vip["id"]).json()
    assert held["status"] == "pending_payment" and held["amount_minor"] == 250000 and held["currency"] == "NGN"
    assert held["ticket_code"] is None and held["hold_expires_at"]
    required = names(captured, "events.registration.payment_required")[0]
    assert required["amount_minor"] == 250000 and required["registration_id"] == held["id"]
    assert register(auth_client(third_user), event, ticket_type=vip["id"]).json()["status"] == "waitlisted"
    from university.core.exceptions import Conflict, ValidationError

    with pytest.raises(ValidationError):
        services.confirm_payment(registration_id=held["id"], reference="ps_1", amount_minor=100, currency="NGN")
    # The hold runs out: the seat passes to the waitlist (as a new hold).
    Registration.objects.filter(pk=held["id"]).update(hold_expires_at=timezone.now() - dt.timedelta(minutes=1))
    assert services.release_expired_holds() == 1
    assert mine(auth_client(other_user), event)["status"] == "expired"
    nxt = mine(auth_client(third_user), event)
    assert nxt["status"] == "pending_payment"
    with pytest.raises(Conflict):
        services.confirm_payment(registration_id=held["id"], reference="ps_1", amount_minor=250000, currency="NGN")
    done = services.confirm_payment(registration_id=nxt["id"], reference="ps_2", amount_minor=250000, currency="NGN")
    assert done.status == RegistrationStatus.CONFIRMED
    again = services.confirm_payment(registration_id=nxt["id"], reference="ps_2", amount_minor=250000, currency="NGN")
    assert again.pk == done.pk  # Idempotent webhook retries.
    assert mine(auth_client(third_user), event)["ticket_code"]
    price_change = host.patch(f"{BASE}/{event['id']}/ticket-types/{vip['id']}/", {"price_minor": 1}, format="json")
    assert price_change.json()["error"]["code"] == "price_locked"


# -------------------------------------------------------- privacy, check-in
@pytest.mark.security
def test_online_link_only_for_confirmed_attendees(auth_client, api_client, user, other_user, third_user):
    host = auth_client(user)
    event = published(host, format="hybrid", online_url="https://meet.example.com/secret", capacity=1)
    assert api_client.get(f"{BASE}/{event['id']}/").json()["online_url"] is None
    assert host.get(f"{BASE}/{event['id']}/").json()["online_url"] == "https://meet.example.com/secret"
    register(auth_client(other_user), event)
    register(auth_client(third_user), event)  # Waitlisted.
    assert auth_client(other_user).get(f"{BASE}/{event['id']}/").json()["online_url"].endswith("secret")
    assert auth_client(third_user).get(f"{BASE}/{event['id']}/").json()["online_url"] is None

    def unfolded(response):
        return response.content.decode().replace("\r\n ", "")

    assert "secret" not in unfolded(api_client.get(f"{BASE}/{event['id']}/calendar.ics"))
    ics = auth_client(other_user).get(f"{BASE}/{event['id']}/calendar.ics")
    assert ics["Content-Type"].startswith("text/calendar") and "meet.example.com/secret" in unfolded(ics)


def test_calendar_file(auth_client, api_client, user):
    host = auth_client(user)
    event = published(host, title="Talks; Q&A, and more\\", summary="Line one\nLine two " + "x" * 120)
    body = api_client.get(f"{BASE}/{event['id']}/calendar.ics").content.decode()
    assert body.startswith("BEGIN:VCALENDAR\r\n") and body.endswith("END:VCALENDAR\r\n")
    assert "SUMMARY:Talks\\; Q&A\\, and more\\\\" in body
    assert all(len(line.encode()) <= 75 for line in body.split("\r\n"))
    host.post(f"{BASE}/{event['id']}/cancel/", {"reason": "Rain"}, format="json")
    assert "STATUS:CANCELLED" in api_client.get(f"{BASE}/{event['id']}/calendar.ics").content.decode()


@pytest.mark.security
def test_check_in(auth_client, user, other_user, third_user, fourth_user):
    host = auth_client(user)
    event = published(host)
    register(auth_client(other_user), event)
    code = mine(auth_client(other_user), event)["ticket_code"]
    assert len(code) == 23 and code.count("-") == 3
    stranger = auth_client(fourth_user)
    assert stranger.post(f"{BASE}/{event['id']}/check-in/", {"code": code}, format="json").status_code == 403
    host.post(f"{BASE}/{event['id']}/organizers/", {"user_id": str(third_user.pk), "role": "checkin"}, format="json")
    door = auth_client(third_user)
    result = door.post(f"{BASE}/{event['id']}/check-in/", {"code": code.lower().replace("-", " ")}, format="json")
    assert result.status_code == 200 and result.json()["attendee"]["handle"] == "grace"
    twice = door.post(f"{BASE}/{event['id']}/check-in/", {"code": code}, format="json")
    assert twice.status_code == 409 and twice.json()["error"]["code"] == "already_checked_in"
    assert (
        door.post(f"{BASE}/{event['id']}/check-in/", {"code": "AAAAA-BBBBB-CCCCC-DDDDD"}, format="json").status_code
        == 404
    )
    # Door staff see attendees but can't edit the event or export contacts.
    assert door.get(f"{BASE}/{event['id']}/registrations/").json()["count"] == 1
    assert door.patch(f"{BASE}/{event['id']}/", {"title": "x"}, format="json").status_code == 403
    assert door.get(f"{BASE}/{event['id']}/registrations/export.csv").status_code == 403
    assert (
        auth_client(other_user).delete(f"{BASE}/{event['id']}/registration/").json()["error"]["code"]
        == "already_checked_in"
    )


@pytest.mark.security
def test_ticket_codes_are_not_stored_and_survive_key_rotation(settings, auth_client, user, other_user):
    event = published(auth_client(user))
    register(auth_client(other_user), event)
    code = mine(auth_client(other_user), event)["ticket_code"]
    registration = Registration.objects.get()
    assert code.replace("-", "") not in registration.ticket_lookup.upper()
    settings.UNIVERSITY = {"SECURITY": {"HMAC_KEY": "new-key-" + "k" * 40, "HMAC_KEY_FALLBACKS": [settings.SECRET_KEY]}}
    assert mine(auth_client(other_user), event)["ticket_code"] == code
    assert services.check_in(actor=user, event_id=event["id"], code=code).checked_in_at


def test_attendee_export_is_safe(auth_client, user, other_user, third_user):
    host = auth_client(user)
    event = published(host)
    other_user.display_name = '=HYPERLINK("http://evil")'
    other_user.save()
    register(auth_client(other_user), event, share_contact=True)
    register(auth_client(third_user), event)
    body = host.get(f"{BASE}/{event['id']}/registrations/export.csv").content.decode()
    assert "'=HYPERLINK" in body
    assert other_user.email in body and third_user.email not in body
    attendees = {a["user"]["handle"]: a for a in host.get(f"{BASE}/{event['id']}/registrations/").json()["results"]}
    assert attendees["grace"]["email"] == other_user.email and attendees["ngozi"]["email"] is None


# -------------------------------------------------------------- organizers
def test_organizer_ranks(auth_client, user, other_user, third_user, fourth_user):
    owner = auth_client(user)
    event = create(owner)
    url = f"{BASE}/{event['id']}/organizers/"
    assert owner.post(url, {"user_id": str(other_user.pk), "role": "organizer"}, format="json").status_code == 201
    organizer = auth_client(other_user)
    assert organizer.post(url, {"user_id": str(third_user.pk), "role": "organizer"}, format="json").status_code == 403
    assert organizer.post(url, {"user_id": str(third_user.pk), "role": "checkin"}, format="json").status_code == 201
    assert organizer.delete(f"{url}{user.pk}/").json()["error"]["code"] == "owner_must_transfer"
    assert (
        organizer.post(
            f"{BASE}/{event['id']}/transfer-ownership/", {"user_id": str(other_user.pk)}, format="json"
        ).status_code
        == 403
    )
    assert (
        owner.post(
            f"{BASE}/{event['id']}/transfer-ownership/", {"user_id": str(fourth_user.pk)}, format="json"
        ).status_code
        == 400
    )
    assert (
        owner.post(
            f"{BASE}/{event['id']}/transfer-ownership/", {"user_id": str(other_user.pk)}, format="json"
        ).status_code
        == 204
    )
    roles = {o["user"]["handle"]: o["role"] for o in organizer.get(url).json()}
    assert roles == {"grace": "owner", "ada": "organizer", "ngozi": "checkin"}
    assert auth_client(third_user).delete(f"{url}{third_user.pk}/").status_code == 204  # Leaving.


# ---------------------------------------------------------------- notices
def test_cancel_and_reschedule_notify_attendees(auth_client, user, other_user, third_user, captured):
    host = auth_client(user)
    event = published(host, capacity=1)
    register(auth_client(other_user), event)
    register(auth_client(third_user), event)
    host.patch(f"{BASE}/{event['id']}/", {"starts_at": soon(72), "ends_at": soon(75)}, format="json")
    notices = names(captured, "events.attendee.notice")
    assert {(n["user_id"], n["kind"]) for n in notices} == {
        (str(other_user.pk), "rescheduled"),
        (str(third_user.pk), "rescheduled"),
    }
    host.patch(f"{BASE}/{event['id']}/", {"summary": "New summary"}, format="json")  # Not a reschedule.
    assert len(names(captured, "events.attendee.notice")) == 2
    host.post(f"{BASE}/{event['id']}/cancel/", {"reason": "Venue flooded"}, format="json")
    assert sum(n["kind"] == "cancelled" for n in names(captured, "events.attendee.notice")) == 2
    assert register(auth_client(user), event).json()["error"]["code"] == "registration_closed"
    assert (
        host.patch(f"{BASE}/{event['id']}/", {"title": "x"}, format="json").json()["error"]["code"] == "event_cancelled"
    )


def test_reminders_are_sent_once(auth_client, user, other_user, captured):
    event = published(auth_client(user), starts_at=soon(5), ends_at=soon(6))
    later = published(auth_client(user), starts_at=soon(60), ends_at=soon(61))
    register(auth_client(other_user), event)
    register(auth_client(other_user), later)
    assert services.send_reminders() == 1
    assert services.send_reminders() == 0
    notices = names(captured, "events.attendee.notice")
    assert notices == [
        {
            "event_id": event["id"],
            "registration_id": mine(auth_client(other_user), event)["id"],
            "user_id": str(other_user.pk),
            "kind": "reminder",
        }
    ]


# -------------------------------------------------------------- moderation
@pytest.mark.security
def test_event_adapter_policy(auth_client, api_client, user, other_user):
    from university.core.content import get_moderatable_adapter

    host = auth_client(user)
    event = published(host)
    register(auth_client(other_user), event)
    adapter = get_moderatable_adapter("events.event")
    ref = adapter.resolve(event["id"])
    assert ref.author_id == str(user.pk) and ref.scope is None and "Lagos Tech Meetup" in ref.excerpt
    adapter.hide(event["id"], reason="Scam")
    assert api_client.get(f"{BASE}/{event['id']}/").status_code == 404
    assert api_client.get(f"{BASE}/").json()["count"] == 0
    assert host.get(f"{BASE}/{event['id']}/").json()["is_hidden"] is True
    assert register(auth_client(create_user("x@example.com", handle="xavier")), event).status_code == 404
    adapter.restore(event["id"])
    assert api_client.get(f"{BASE}/{event['id']}/").status_code == 200
    adapter.remove(event["id"], reason="Scam")
    removed = Event.all_objects.get(pk=event["id"])
    assert removed.deleted_at is not None and removed.status == "cancelled"


def test_hosted_events_route_reports_to_the_host(user):
    from university.core.content import get_moderatable_adapter

    assign_role(user=user, role_key="events_manager", scope=Scope("institution", INST))
    event = services.create_event(
        creator=user,
        data={
            "title": "Hosted",
            "starts_at": timezone.now() + dt.timedelta(days=2),
            "ends_at": timezone.now() + dt.timedelta(days=2, hours=1),
        },
        scope_type="institution",
        scope_id=INST,
    )
    assert get_moderatable_adapter("events.event").resolve(event.pk).scope == ("institution", INST)


# ------------------------------------------------------------ misc surface
def test_cover_upload(auth_client, user):
    host = auth_client(user)
    event = create(host)
    ok = host.post(f"{BASE}/{event['id']}/cover/", {"file": SimpleUploadedFile("c.png", PNG)}, format="multipart")
    assert ok.status_code == 200 and ok.json()["cover_url"].endswith(".png")
    bad = host.post(
        f"{BASE}/{event['id']}/cover/",
        {"file": SimpleUploadedFile("c.png", b"<svg onload=alert(1)>")},
        format="multipart",
    )
    assert bad.status_code == 400
    assert host.delete(f"{BASE}/{event['id']}/cover/").json()["cover_url"] is None


def test_sessions(auth_client, api_client, user):
    host = auth_client(user)
    event = published(host)
    url = f"{BASE}/{event['id']}/sessions/"
    start = Event.objects.get(pk=event["id"]).starts_at
    first = {
        "title": "Keynote",
        "starts_at": start.isoformat(),
        "ends_at": (start + dt.timedelta(hours=1)).isoformat(),
        "speakers": [{"name": "Dr. Adaeze", "title": "CTO"}],
    }
    assert host.post(url, first, format="json").status_code == 201
    outside = {**first, "starts_at": (start - dt.timedelta(hours=1)).isoformat()}
    assert host.post(url, outside, format="json").status_code == 400
    assert host.post(url, {**first, "speakers": [{"title": "no name"}]}, format="json").status_code == 400
    assert [s["title"] for s in api_client.get(url).json()] == ["Keynote"]
    assert api_client.get(f"{BASE}/{event['id']}/").json()["sessions"][0]["speakers"][0]["name"] == "Dr. Adaeze"


def test_venues(auth_client, api_client, user, other_user):
    host = auth_client(user)
    venue = host.post(
        "/api/v1/venues/", {"name": "Main Auditorium", "city": "Nsukka", "country": "ng"}, format="json"
    ).json()
    assert venue["country"] == "NG"
    assert (
        auth_client(other_user).patch(f"/api/v1/venues/{venue['id']}/", {"name": "Mine"}, format="json").status_code
        == 403
    )
    scoped = host.post(
        "/api/v1/venues/", {"name": "Hall", "scope_type": "institution", "scope_id": INST}, format="json"
    )
    assert scoped.status_code == 403
    event = published(host, venue=venue["id"], location_details="")
    assert event["venue"]["name"] == "Main Auditorium"
    assert api_client.get(f"{BASE}/", {"city": "nsukka"}).json()["count"] == 1


def test_export_purge_and_retention(auth_client, user, other_user, third_user):
    from university.core.hooks import Hook, hooks
    from university.core.retention import run_retention

    event = published(auth_client(user), capacity=1)
    register(auth_client(other_user), event)
    register(auth_client(third_user), event)
    exported = hooks.collect(Hook.USER_EXPORT_DATA, other_user)
    assert exported["event_registrations"][0]["status"] == "confirmed"
    assert hooks.collect(Hook.USER_EXPORT_DATA, user)["events_organized"][0]["role"] == "owner"
    hooks.call(Hook.USER_PURGE, other_user.pk)
    assert not Registration.objects.filter(user=other_user).exists()
    assert mine(auth_client(third_user), event)["status"] == "confirmed"  # The seat moved on.
    Event.objects.filter(pk=event["id"]).update(
        starts_at=timezone.now() - dt.timedelta(days=800), ends_at=timezone.now() - dt.timedelta(days=799)
    )
    assert run_retention(only=["events.past_registrations"])["events.past_registrations"] == 1


def test_my_lists(auth_client, user, other_user):
    event = published(auth_client(user))
    register(auth_client(other_user), event)
    assert auth_client(other_user).get("/api/v1/me/event-registrations/", {"upcoming": "true"}).json()["count"] == 1
    assert auth_client(other_user).get("/api/v1/me/event-registrations/", {"upcoming": "false"}).json()["count"] == 0
    assert auth_client(user).get("/api/v1/me/events/").json()["results"][0]["viewer"]["role"] == "owner"


@pytest.mark.security
def test_cancelled_tickets_cannot_check_in(auth_client, user, other_user):
    host = auth_client(user)
    event = published(host)
    register(auth_client(other_user), event)
    saved = mine(auth_client(other_user), event)["ticket_code"]  # e.g. a screenshot
    auth_client(other_user).delete(f"{BASE}/{event['id']}/registration/")
    assert mine(auth_client(other_user), event)["ticket_code"] is None
    rejected = host.post(f"{BASE}/{event['id']}/check-in/", {"code": saved}, format="json")
    assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "ticket_not_valid"
