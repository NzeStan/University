"""0.1.2 features composed end to end: anonymous inbox, announcements and opportunities."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.core.testing import create_user
from university.institution.models import Institution, InstitutionMembership, InstitutionType
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db


def aged(email, handle):
    user = create_user(email, handle=handle)
    type(user).objects.filter(pk=user.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
    user.refresh_from_db()
    return user


def notifications(client):
    return client.get("/api/v1/notifications/").json()["results"]


@pytest.mark.security
def test_inbox_messages_notify_the_recipient_without_naming_the_sender(auth_client):
    owner, sender = aged("owner@example.com", "owner"), aged("sender@example.com", "sender")
    auth_client(owner).patch("/api/v1/anonymous/me/inbox/", {"enabled": True}, format="json")
    auth_client(sender).post("/api/v1/anonymous/inboxes/owner/messages/", {"body": "Hello there"}, format="json")
    auth_client(sender).post("/api/v1/anonymous/inboxes/owner/messages/", {"body": "Me again"}, format="json")
    items = notifications(auth_client(owner))
    assert len(items) == 1  # Grouped: one notification for the inbox.
    assert items[0]["title"] == "You have a new anonymous message." and items[0]["actor"] is None
    assert "sender" not in str(items[0]) and str(sender.pk) not in str(items[0])


def test_urgent_announcements_reach_members(auth_client):
    uni = Institution.objects.create(
        name="Example University",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
        is_verified=True,
    )
    officer, student = create_user("comms@exu.edu.ng", handle="comms"), create_user("s@exu.edu.ng", handle="student")
    assign_role(user=officer, role_key="institution_communications", scope=Scope("institution", str(uni.pk)))
    InstitutionMembership.objects.create(user=student, institution=uni, role="student", status="verified")
    auth_client(officer).post(
        f"/api/v1/institutions/{uni.pk}/announcements/",
        {
            "title": "Campus closed today",
            "body": "Stay safe.",
            "priority": "urgent",
            "audience": "public",
            "publish": True,
        },
        format="json",
    )
    [item] = notifications(auth_client(student))
    assert item["title"] == "Urgent announcement: Campus closed today" and item["category"] == "urgent_announcements"
    results = auth_client(student).get("/api/v1/search/", {"q": "campus closed"}).json()
    assert [r["content_type"] for r in results] == ["institution.announcement"]


def test_applications_notify_both_sides(auth_client, api_client):
    poster, applicant = create_user("hr@example.com", handle="hiring"), create_user("a@example.com", handle="applicant")
    job = (
        auth_client(poster)
        .post(
            "/api/v1/opportunities/",
            {
                "kind": "job",
                "title": "Campus ambassador",
                "organization_name": "GistCo",
                "description": "Spread the word.",
                "publish": True,
            },
            format="json",
        )
        .json()
    )
    application = (
        auth_client(applicant)
        .post(f"/api/v1/opportunities/{job['id']}/apply/", {"cover_note": "Me!"}, format="json")
        .json()
    )
    assert notifications(auth_client(poster))[0]["title"] == "@applicant applied to Campus ambassador at GistCo"
    auth_client(poster).patch(
        f"/api/v1/opportunities/applications/{application['id']}/", {"status": "hired"}, format="json"
    )
    assert (
        notifications(auth_client(applicant))[0]["title"]
        == "Good news: you were selected for Campus ambassador at GistCo"
    )
    found = api_client.get("/api/v1/search/", {"q": "ambassador"}).json()
    assert [r["content_type"] for r in found] == ["opportunities.opportunity"]
