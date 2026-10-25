"""Moderation + anonymous composed with institution and social."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.institution import services as institution
from university.institution.models import Institution, InstitutionMembership, InstitutionType
from university.moderation.models import ModerationCase
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db


@pytest.fixture
def uni(db):
    return Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )


def member(user, uni):
    membership = institution.request_membership(user=user, institution=uni, role="student")
    InstitutionMembership.objects.filter(pk=membership.pk).update(status="verified")
    type(user).objects.filter(pk=user.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
    user.refresh_from_db()


def test_all_content_types_registered():
    from university.core.content import content_types

    assert set(content_types()) >= {
        "social.post",
        "social.comment",
        "anonymous.post",
        "anonymous.comment",
        "users.user",
    }


def test_social_posts_are_moderated_through_adapters(auth_client, user, other_user):
    mod = auth_client(user).__class__()
    from university.core.testing import create_user

    moderator = create_user("mod@example.com", handle="modx")
    assign_role(user=moderator, role_key="platform_moderator")
    post = auth_client(user).post("/api/v1/social/posts/", {"body": "rude"}, format="json").json()
    report = auth_client(other_user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "social.post", "object_id": post["id"], "reason": "harassment"},
        format="json",
    )
    assert report.status_code == 201
    case = ModerationCase.objects.get()
    assert case.target_author == user
    assert (
        auth_client(moderator)
        .post(f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "x"}, format="json")
        .status_code
        == 201
    )
    assert auth_client(other_user).get(f"/api/v1/social/posts/{post['id']}/").status_code == 404
    del mod


def test_restriction_applies_to_social_and_anonymous(auth_client, user, other_user, uni):
    from university.core.testing import create_user

    member(user, uni)
    moderator = create_user("mod@example.com", handle="modx")
    assign_role(user=moderator, role_key="platform_moderator")
    post = auth_client(user).post("/api/v1/social/posts/", {"body": "spam spam"}, format="json").json()
    auth_client(other_user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "social.post", "object_id": post["id"], "reason": "spam"},
        format="json",
    )
    case = ModerationCase.objects.get()
    auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/",
        {"action": "restrict", "reason": "spam", "duration_hours": 24, "restriction_kind": "posting"},
        format="json",
    )
    social = auth_client(user).post("/api/v1/social/posts/", {"body": "again"}, format="json")
    anon = auth_client(user).post(
        "/api/v1/anonymous/posts/",
        {"body": "again", "visibility": "institution", "audience_id": str(uni.pk)},
        format="json",
    )
    assert social.json()["error"]["code"] == anon.json()["error"]["code"] == "content_creation_restricted"
    # Commenting is still allowed under a posting restriction.
    other_post = auth_client(other_user).post("/api/v1/social/posts/", {"body": "hello"}, format="json").json()
    assert (
        auth_client(user)
        .post(f"/api/v1/social/posts/{other_post['id']}/comments/", {"body": "ok"}, format="json")
        .status_code
        == 201
    )


def test_anonymous_board_uses_real_institution_membership(auth_client, user, other_user, uni):
    member(user, uni)
    created = auth_client(user).post(
        "/api/v1/anonymous/posts/",
        {"body": "EXU confession", "visibility": "institution", "audience_id": str(uni.pk)},
        format="json",
    )
    assert created.status_code == 201
    assert auth_client(other_user).get("/api/v1/anonymous/posts/").json()["results"] == []
    member(other_user, uni)
    feed = auth_client(other_user).get("/api/v1/anonymous/posts/").json()["results"]
    assert [p["body"] for p in feed] == ["EXU confession"]
    assert str(user.pk) not in str(feed)


def test_social_blocks_do_not_affect_anonymous_visibility(auth_client, user, other_user, uni):
    member(user, uni)
    member(other_user, uni)
    auth_client(user).post(
        "/api/v1/anonymous/posts/",
        {"body": "anon", "visibility": "institution", "audience_id": str(uni.pk)},
        format="json",
    )
    auth_client(other_user).post(f"/api/v1/social/users/{user.pk}/block/")
    assert len(auth_client(other_user).get("/api/v1/anonymous/posts/").json()["results"]) == 1


@pytest.mark.security
def test_institutions_are_named_but_not_reportable(auth_client, user, uni):
    from university.core.content import content_types
    from university.core.testing import create_user
    from university.moderation.services.cases import open_case

    assert "institution.institution" in content_types()
    assert "institution.institution" not in content_types(moderatable=True)
    assert set(content_types(moderatable=True)) >= {
        "social.post",
        "anonymous.post",
        "community.community",
        "users.user",
    }
    report = auth_client(user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "institution.institution", "object_id": str(uni.pk), "reason": "spam"},
        format="json",
    )
    unknown = auth_client(user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "nonexistent.type", "object_id": str(uni.pk), "reason": "spam"},
        format="json",
    )
    # Display-only types look exactly like unknown ones.
    assert report.status_code == unknown.status_code == 404
    assert report.json()["error"]["message"] == unknown.json()["error"]["message"]
    moderator = create_user("mod@example.com", handle="modx")
    assign_role(user=moderator, role_key="platform_moderator")
    with pytest.raises(Exception, match="Unknown content type"):
        open_case(actor=moderator, content_type="institution.institution", object_id=uni.pk)
    assert not ModerationCase.objects.exists()
