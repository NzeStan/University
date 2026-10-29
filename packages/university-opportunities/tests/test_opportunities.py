"""Opportunities: posting, discovery, audiences, applications, CV privacy, verification and moderation."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.utils import timezone

from tests.audience.apps import MEMBERS
from university.core.testing import create_user
from university.opportunities.models import Application, Opportunity
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
BASE = "/api/v1/opportunities"
PDF = b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n"


@pytest.fixture(autouse=True)
def _members():
    MEMBERS.clear()
    yield
    MEMBERS.clear()


def job(**extra):
    return {
        "kind": "internship",
        "title": "Backend engineering intern",
        "organization_name": "Lagos Fintech Ltd",
        "description": "Build APIs with Python and Django. Paid monthly.",
        "location": "Lagos",
        "work_mode": "hybrid",
        "pay_min_minor": 15000000,
        "pay_max_minor": 25000000,
        "pay_period": "month",
        **extra,
    }


def post(client, publish=True, **extra):
    response = client.post(f"{BASE}/", {**job(**extra), "publish": publish}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_post_publish_and_discover(auth_client, api_client, user):
    created = post(auth_client(user))
    assert created["status"] == "open" and created["verified"] is False
    assert created["poster"]["handle"] == user.handle and created["viewer"]["is_poster"] is True
    listed = api_client.get(f"{BASE}/").json()
    assert listed["count"] == 1 and listed["results"][0]["id"] == created["id"]
    assert api_client.get(f"{BASE}/", {"q": "django"}).json()["count"] == 1
    assert api_client.get(f"{BASE}/", {"kind": "job"}).json()["count"] == 0
    draft = post(auth_client(user), publish=False, title="Not yet")
    assert api_client.get(f"{BASE}/{draft['id']}/").status_code == 404
    assert auth_client(user).get(f"{BASE}/{draft['id']}/").status_code == 200


def test_validation_rules(auth_client, user):
    client = auth_client(user)
    assert client.post(f"{BASE}/", job(pay_min_minor=50, pay_max_minor=10), format="json").status_code == 400
    assert client.post(f"{BASE}/", job(apply_method="external"), format="json").json()["error"]["details"]["apply_url"]
    assert client.post(f"{BASE}/", job(currency="XYZ"), format="json").status_code == 400
    past = (timezone.now() - dt.timedelta(days=1)).isoformat()
    assert client.post(f"{BASE}/", job(deadline=past), format="json").status_code == 400
    unpaid = client.post(f"{BASE}/", job(pay_period="unpaid"), format="json").json()
    assert unpaid["pay_min_minor"] is None and unpaid["pay_max_minor"] is None


def test_unverified_emails_cannot_post(auth_client):
    newbie = create_user("new@example.com", handle="newbie", verified=False)
    assert auth_client(newbie).post(f"{BASE}/", job(), format="json").json()["error"]["code"] == "email_not_verified"


def test_open_postings_are_capped(auth_client, user, settings):
    settings.UNIVERSITY = {"OPPORTUNITIES": {"MAX_OPEN_PER_USER": 1}}
    post(auth_client(user))
    second = auth_client(user).post(f"{BASE}/", {**job(title="Another"), "publish": True}, format="json")
    assert second.json()["error"]["code"] == "open_limit"


def test_institution_only_postings(auth_client, api_client, user, other_user):
    MEMBERS[str(user.pk)] = [("institution", "inst-1")]
    assert (
        auth_client(other_user)
        .post(f"{BASE}/", job(audience="institution", scope_id="inst-1"), format="json")
        .status_code
        == 400
    )
    created = post(auth_client(user), audience="institution", scope_id="inst-1")
    assert api_client.get(f"{BASE}/").json()["count"] == 0
    assert auth_client(other_user).get(f"{BASE}/{created['id']}/").status_code == 404
    MEMBERS[str(other_user.pk)] = [("institution", "inst-1")]
    assert auth_client(other_user).get(f"{BASE}/").json()["count"] == 1


@pytest.mark.security
def test_applying_and_cv_privacy(auth_client, user, other_user):
    created = post(auth_client(user))
    stranger = create_user("s@example.com", handle="stranger")
    applied = auth_client(other_user).post(
        f"{BASE}/{created['id']}/apply/",
        {"cover_note": "I love Django.", "resume": SimpleUploadedFile("cv.pdf", PDF, content_type="application/pdf")},
        format="multipart",
    )
    assert applied.status_code == 201, applied.json()
    application = applied.json()
    assert application["has_resume"] and application["status"] == "submitted"
    assert (
        auth_client(other_user).post(f"{BASE}/{created['id']}/apply/", {}, format="json").json()["error"]["code"]
        == "already_applied"
    )
    assert (
        auth_client(user).post(f"{BASE}/{created['id']}/apply/", {}, format="json").json()["error"]["code"]
        == "own_opportunity"
    )
    # Only the poster and the applicant can see the application and its CV.
    resume = f"{BASE}/applications/{application['id']}/resume/"
    assert auth_client(user).get(resume).status_code == 200
    assert auth_client(other_user).get(resume)["Cache-Control"] == "private, no-store"
    assert auth_client(stranger).get(resume).status_code == 404
    assert auth_client(stranger).get(f"{BASE}/{created['id']}/applications/").status_code == 404
    listed = auth_client(user).get(f"{BASE}/{created['id']}/applications/").json()["results"]
    assert [a["applicant"]["handle"] for a in listed] == [other_user.handle]
    stored = Application.objects.get().resume
    assert "cv.pdf" not in stored.name and stored.name.endswith(".pdf")


@pytest.mark.security
def test_cv_uploads_must_be_real_pdfs(auth_client, user, other_user):
    created = post(auth_client(user))
    fake = SimpleUploadedFile("cv.pdf", b"<html><script>alert(1)</script>", content_type="application/pdf")
    response = auth_client(other_user).post(f"{BASE}/{created['id']}/apply/", {"resume": fake}, format="multipart")
    assert response.status_code == 400 and "resume" in response.json()["error"]["details"]


def test_decisions_and_withdrawal(auth_client, user, other_user):
    created = post(auth_client(user))
    application = (
        auth_client(other_user).post(f"{BASE}/{created['id']}/apply/", {"cover_note": "Hi"}, format="json").json()
    )
    url = f"{BASE}/applications/{application['id']}/"
    assert auth_client(other_user).patch(url, {"status": "hired"}, format="json").status_code == 404
    assert auth_client(user).patch(url, {"status": "shortlisted"}, format="json").json()["status"] == "shortlisted"
    mine = auth_client(other_user).get(f"{BASE}/me/applications/").json()["results"]
    assert mine[0]["status"] == "shortlisted"
    assert (
        auth_client(other_user).get(f"{BASE}/{created['id']}/").json()["viewer"]["application_status"] == "shortlisted"
    )
    assert auth_client(other_user).post(f"{url}withdraw/").json()["status"] == "withdrawn"
    assert auth_client(user).patch(url, {"status": "hired"}, format="json").json()["error"]["code"] == "withdrawn"


def test_closed_and_expired_postings_stop_applications(auth_client, user, other_user):
    created = post(auth_client(user))
    auth_client(user).post(f"{BASE}/{created['id']}/status/", {"action": "close"}, format="json")
    assert (
        auth_client(other_user).post(f"{BASE}/{created['id']}/apply/", {}, format="json").json()["error"]["code"]
        == "closed"
    )
    soon = post(auth_client(user), title="Soon", deadline=(timezone.now() + dt.timedelta(minutes=5)).isoformat())
    Opportunity.objects.filter(pk=soon["id"]).update(deadline=timezone.now() - dt.timedelta(seconds=1))
    from university.opportunities.services import close_expired

    assert close_expired() == 1
    assert Opportunity.objects.get(pk=soon["id"]).status == "closed"


def test_external_postings_link_out(auth_client, user, other_user):
    created = post(auth_client(user), apply_method="external", apply_url="https://careers.example.com/apply")
    response = auth_client(other_user).post(f"{BASE}/{created['id']}/apply/", {}, format="json")
    assert response.json()["error"]["code"] == "apply_elsewhere"


def test_saving(auth_client, user, other_user):
    created = post(auth_client(user))
    client = auth_client(other_user)
    assert client.post(f"{BASE}/{created['id']}/save/").status_code == 204
    assert client.get(f"{BASE}/{created['id']}/").json()["viewer"]["saved"] is True
    assert [o["id"] for o in client.get(f"{BASE}/me/saved/").json()["results"]] == [created["id"]]
    client.delete(f"{BASE}/{created['id']}/save/")
    assert client.get(f"{BASE}/me/saved/").json()["results"] == []


@pytest.mark.security
def test_only_staff_can_mark_verified_employers(auth_client, user, staff_user):
    created = post(auth_client(user))
    assert (
        auth_client(user).post(f"{BASE}/{created['id']}/verify/", {"verified": True}, format="json").status_code == 403
    )
    assign_role(user=staff_user, role_key="opportunities_curator")
    assert (
        auth_client(staff_user)
        .post(f"{BASE}/{created['id']}/verify/", {"verified": True}, format="json")
        .json()["verified"]
        is True
    )


def test_moderation_hides_postings(auth_client, api_client, user):
    from university.opportunities.content import OpportunityAdapter

    created = post(auth_client(user))
    adapter = OpportunityAdapter()
    assert adapter.moderatable and adapter.is_author(created["id"], user)
    adapter.hide(created["id"], reason="Pay-to-apply scam")
    assert api_client.get(f"{BASE}/").json()["count"] == 0
    assert api_client.get(f"{BASE}/{created['id']}/").status_code == 404
    reopen = auth_client(user).post(f"{BASE}/{created['id']}/status/", {"action": "reopen"}, format="json")
    assert reopen.json()["error"]["code"] == "hidden"
    adapter.restore(created["id"])
    assert api_client.get(f"{BASE}/").json()["count"] == 1


def test_export_purge_and_retention(auth_client, user, other_user):
    from university.core.retention import run_retention
    from university.opportunities.integrations import export_data, purge

    created = post(auth_client(user))
    auth_client(other_user).post(
        f"{BASE}/{created['id']}/apply/",
        {"resume": SimpleUploadedFile("cv.pdf", PDF, content_type="application/pdf")},
        format="multipart",
    )
    exported = export_data(other_user)["opportunities"]["applications"]
    assert [str(a["opportunity"]) for a in exported] == [created["id"]]
    auth_client(user).post(f"{BASE}/{created['id']}/status/", {"action": "close"}, format="json")
    Opportunity.objects.filter(pk=created["id"]).update(closed_at=timezone.now() - dt.timedelta(days=400))
    assert run_retention(only=["opportunities.applications"])["opportunities.applications"] == 1
    assert not Application.objects.exists()
    purge(user.pk)
    assert not Opportunity.all_objects.exists()
