"""Official announcements: who can publish, who can read, targeting, notices and verification."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.core.events import event_bus
from university.core.testing import create_user
from university.institution.constants import MembershipStatus
from university.institution.models import Campus, Institution, InstitutionMembership, InstitutionType
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
BASE = "/api/v1"


@pytest.fixture
def uni(db):
    return Institution.objects.create(
        name="Example University", short_name="EXU", slug="exu", country="NG",
        type=InstitutionType.objects.get(key="university"), is_verified=True,
    )  # fmt: skip


@pytest.fixture
def comms(uni):
    officer = create_user("comms@exu.edu.ng", handle="comms")
    assign_role(user=officer, role_key="institution_communications", scope=Scope("institution", str(uni.pk)))
    return officer


def member(uni, email, handle, campus=None):
    user = create_user(email, handle=handle)
    InstitutionMembership.objects.create(
        user=user, institution=uni, role="student", status=MembershipStatus.VERIFIED, campus=campus
    )
    return user


def url(uni, suffix=""):
    return f"{BASE}/institutions/{uni.pk}/announcements/{suffix}"


def announce(client, uni, **data):
    payload = {"title": "Exam timetable released", "body": "Check the portal.", **data}
    response = client.post(url(uni), payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_only_the_communications_team_can_publish(auth_client, uni, comms, user):
    assert auth_client(user).post(url(uni), {"title": "Fake", "body": "Not official"}, format="json").status_code == 403
    draft = announce(auth_client(comms), uni)
    assert draft["status"] == "draft" and draft["verified"] is True
    assert draft["institution"]["name"] == "Example University"
    assert auth_client(user).post(url(uni, f"{draft['id']}/publish/")).status_code == 403
    published = auth_client(comms).post(url(uni, f"{draft['id']}/publish/")).json()
    assert published["status"] == "published" and published["published_at"]
    # Another institution's officer can't publish here.
    other = Institution.objects.create(name="Other", slug="other", country="NG", type=uni.type)
    outsider = create_user("x@other.edu", handle="otherofficer")
    assign_role(user=outsider, role_key="institution_communications", scope=Scope("institution", str(other.pk)))
    assert auth_client(outsider).post(url(uni), {"title": "Spoof", "body": "x"}, format="json").status_code == 403


def test_audiences_and_drafts(auth_client, api_client, uni, comms, user):
    student = member(uni, "s@exu.edu.ng", "student1")
    announce(auth_client(comms), uni, title="Open day", audience="public", publish=True)
    announce(auth_client(comms), uni, title="Members only", audience="members", publish=True)
    announce(auth_client(comms), uni, title="Still a draft")
    titles = lambda client: {a["title"] for a in client.get(url(uni)).json()["results"]}  # noqa: E731
    assert titles(api_client) == {"Open day"}
    assert titles(auth_client(user)) == {"Open day"}
    assert titles(auth_client(student)) == {"Open day", "Members only"}
    assert {a["title"] for a in auth_client(comms).get(url(uni), {"status": "draft"}).json()["results"]} == {
        "Still a draft"
    }
    # Non-managers can't peek at drafts by asking.
    assert titles(auth_client(user)) == {"Open day"}
    assert {a["title"] for a in auth_client(student).get(url(uni), {"status": "draft"}).json()["results"]} == {
        "Open day",
        "Members only",
    }


def test_expired_and_archived_disappear(auth_client, api_client, uni, comms):
    a = announce(auth_client(comms), uni, audience="public", publish=True)
    auth_client(comms).post(url(uni, f"{a['id']}/archive/"))
    assert api_client.get(url(uni)).json()["results"] == []
    assert api_client.get(url(uni, f"{a['id']}/")).status_code == 404
    soon = (timezone.now() + dt.timedelta(minutes=5)).isoformat()
    b = announce(auth_client(comms), uni, audience="public", expires_at=soon, publish=True)
    from university.institution.models import Announcement

    Announcement.objects.filter(pk=b["id"]).update(expires_at=timezone.now() - dt.timedelta(seconds=1))
    assert api_client.get(url(uni)).json()["results"] == []
    past = (timezone.now() - dt.timedelta(days=1)).isoformat()
    assert (
        auth_client(comms).post(url(uni), {"title": "x", "body": "y", "expires_at": past}, format="json").status_code
        == 400
    )


def test_publishing_notifies_targeted_verified_members(auth_client, uni, comms, user):
    main = Campus.objects.create(institution=uni, name="Main", slug="main")
    annex = Campus.objects.create(institution=uni, name="Annex", slug="annex")
    on_main = member(uni, "a@exu.edu.ng", "mainstudent", campus=main)
    member(uni, "b@exu.edu.ng", "annexstudent", campus=annex)
    pending = create_user("p@exu.edu.ng", handle="pending1")
    InstitutionMembership.objects.create(user=pending, institution=uni, role="student", status=MembershipStatus.PENDING)
    seen = []
    event_bus.subscribe("institution.announcement.notice", seen.append)
    try:
        announce(
            auth_client(comms),
            uni,
            title="Main campus water outage",
            campus=str(main.pk),
            priority="urgent",
            publish=True,
        )
    finally:
        event_bus.unsubscribe("institution.announcement.notice", seen.append)
    assert [str(e.payload["user_id"]) for e in seen] == [str(on_main.pk)]
    assert seen[0].payload["priority"] == "urgent"


def test_targets_must_belong_to_the_institution(auth_client, uni, comms):
    other = Institution.objects.create(name="Other", slug="other2", country="NG", type=uni.type)
    foreign = Campus.objects.create(institution=other, name="Elsewhere", slug="elsewhere")
    response = auth_client(comms).post(url(uni), {"title": "x", "body": "y", "campus": str(foreign.pk)}, format="json")
    assert response.status_code == 400


def test_my_announcements_and_verification(auth_client, uni, comms):
    student = member(uni, "s2@exu.edu.ng", "student2")
    announce(auth_client(comms), uni, title="Welcome back", publish=True)
    mine = auth_client(student).get(f"{BASE}/me/announcements/").json()["results"]
    assert [a["title"] for a in mine] == ["Welcome back"] and mine[0]["verified"] is True
    Institution.objects.filter(pk=uni.pk).update(is_verified=False)
    assert auth_client(student).get(f"{BASE}/me/announcements/").json()["results"][0]["verified"] is False


def test_published_announcements_are_archived_not_deleted(auth_client, uni, comms):
    a = announce(auth_client(comms), uni, publish=True)
    assert auth_client(comms).delete(url(uni, f"{a['id']}/")).json()["error"]["code"] == "archive_instead"
    draft = announce(auth_client(comms), uni)
    assert auth_client(comms).delete(url(uni, f"{draft['id']}/")).status_code == 204


def test_announcements_are_display_only(uni):
    from university.core.registry import registry

    adapter = registry.content_adapters.get("institution.announcement")
    assert adapter is not None and adapter.moderatable is False
