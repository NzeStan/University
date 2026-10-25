"""Notifications composed with social, moderation, anonymous, community and institution."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.community import services as community_services
from university.core.testing import create_user
from university.moderation.models import ModerationAction, ModerationCase
from university.notifications.models import Notification
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db

NOTIFS = "/api/v1/notifications/"


def aged(user):
    type(user).objects.filter(pk=user.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
    user.refresh_from_db()
    return user


def titles(client):
    return [n["title"] for n in client.get(NOTIFS).json()["results"]]


def post(client, body, **extra):
    response = client.post("/api/v1/social/posts/", {"body": body, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def ngozi(db):
    return create_user("ngozi@example.com", handle="ngozi")


@pytest.fixture
def moderator(db):
    mod = create_user("mod@example.com", handle="modx")
    assign_role(user=mod, role_key="platform_moderator")
    return mod


def test_social_activity_notifies_through_events(auth_client, user, other_user, ngozi):
    ada, grace, ng = auth_client(user), auth_client(other_user), auth_client(ngozi)
    grace.post(f"/api/v1/social/users/{user.pk}/follow/")
    original = post(ada, "Exam timetable is out")
    grace.post(f"/api/v1/social/posts/{original['id']}/reaction/", {"kind": "like"}, format="json")
    ng.post(f"/api/v1/social/posts/{original['id']}/reaction/", {"kind": "like"}, format="json")
    comment = grace.post(f"/api/v1/social/posts/{original['id']}/comments/", {"body": "Thanks!"}, format="json").json()
    # Ngozi replies to Grace and mentions Ada: Grace gets a reply, Ada a mention (not also a comment).
    ng.post(
        f"/api/v1/social/posts/{original['id']}/comments/",
        {"body": "@ada see this", "parent": comment["id"]},
        format="json",
    )
    assert titles(ada) == [
        "@ngozi mentioned you",
        "@grace commented on your post",
        "@ngozi and 1 more reacted to your post",
        "@grace started following you",
    ]
    assert titles(grace) == ["@ngozi replied to your comment"]
    # Deleted content is reported unavailable rather than leaking anything.
    ada.delete(f"/api/v1/social/posts/{original['id']}/")
    reaction = next(n for n in ada.get(NOTIFS).json()["results"] if n["verb"] == "social.reaction")
    assert reaction["target"] == {"type": "social.post", "id": original["id"], "available": False}


@pytest.mark.security
def test_social_blocks_stop_and_remove_notifications(auth_client, user, other_user):
    ada, grace = auth_client(user), auth_client(other_user)
    grace.post(f"/api/v1/social/users/{user.pk}/follow/")
    assert len(titles(ada)) == 1
    ada.post(f"/api/v1/social/users/{other_user.pk}/block/")
    assert titles(ada) == []
    original = post(ada, "hello")
    grace.post(f"/api/v1/social/posts/{original['id']}/reaction/", {"kind": "like"}, format="json")
    assert titles(ada) == []


def test_mention_policy_is_respected(auth_client, user, other_user):
    auth_client(user).patch("/api/v1/social/me/profile/", {"allow_mentions_from": "nobody"}, format="json")
    post(auth_client(other_user), "hey @ada")
    assert titles(auth_client(user)) == []


@pytest.mark.security
def test_moderation_and_appeals_notify_without_naming_moderators(auth_client, user, other_user, moderator, ngozi):
    assign_role(user=ngozi, role_key="platform_moderator")
    original = post(auth_client(user), "rude words")
    auth_client(other_user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "social.post", "object_id": original["id"], "reason": "harassment"},
        format="json",
    )
    case = ModerationCase.objects.get()
    auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "x"}, format="json"
    )
    items = auth_client(user).get(NOTIFS).json()["results"]
    assert [i["title"] for i in items] == ["Some of your content was hidden by the moderators."]
    assert items[0]["actor"] is None and "modx" not in str(items)
    action = ModerationAction.objects.get(action="hide")
    auth_client(user).post(
        "/api/v1/moderation/appeals/",
        {"action_id": str(action.pk), "statement": "This was taken out of context."},
        format="json",
    )
    appeal_id = auth_client(ngozi).get("/api/v1/moderation/appeal-queue/").json()["results"][0]["id"]
    decided = auth_client(ngozi).post(
        f"/api/v1/moderation/appeals/{appeal_id}/decide/", {"overturn": True, "reason": "Context"}, format="json"
    )
    assert decided.status_code == 200, decided.json()
    assert titles(auth_client(user))[:2] == [
        "Your appeal was successful and the decision was reversed.",
        "A moderation decision affecting you was reversed.",
    ]


@pytest.mark.security
def test_anonymous_authors_are_never_notified(auth_client, user, other_user, moderator):
    from university.institution.models import Institution, InstitutionMembership, InstitutionType
    from university.institution.services import request_membership

    uni = Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )
    for person in (user, other_user):
        membership = request_membership(user=person, institution=uni, role="student")
        InstitutionMembership.objects.filter(pk=membership.pk).update(status="verified")
        aged(person)
    anon = (
        auth_client(user)
        .post(
            "/api/v1/anonymous/posts/",
            {"body": "confession", "visibility": "institution", "audience_id": str(uni.pk)},
            format="json",
        )
        .json()
    )
    auth_client(other_user).post(f"/api/v1/anonymous/posts/{anon['id']}/comments/", {"body": "same"}, format="json")
    auth_client(other_user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "anonymous.post", "object_id": anon["id"], "reason": "harassment"},
        format="json",
    )
    case = ModerationCase.objects.get()
    auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "x"}, format="json"
    )
    assert not Notification.objects.filter(recipient=user).exists()


def test_community_notifications_use_visible_names(auth_client, user, other_user):
    club = community_services.create_community(creator=user, data={"name": "Robotics", "privacy": "private"})
    invited = auth_client(user).post(
        f"/api/v1/communities/{club.pk}/invitations/", {"user_id": str(other_user.pk)}, format="json"
    )
    assert invited.status_code in (200, 201), invited.json()
    # Invitees can see the private community, so its name is shown.
    assert titles(auth_client(other_user)) == ["@ada invited you to join Robotics"]
    auth_client(other_user).post(f"/api/v1/communities/{club.pk}/invitations/accept/")
    auth_client(user).post(f"/api/v1/communities/{club.pk}/members/{other_user.pk}/remove/", {}, format="json")
    # Once removed, the private community's name is no longer theirs to see.
    assert titles(auth_client(other_user))[0] == "You were removed from a community."


def test_institution_verification_is_notified(auth_client, user):
    from university.institution.models import Institution, InstitutionType
    from university.institution.services import request_membership, review_membership
    from university.permissions.scopes import Scope

    uni = Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )
    staff = create_user("registrar@example.com", handle="registrar")
    assign_role(user=staff, role_key="institution_admin", scope=Scope("institution", str(uni.pk)))
    membership = request_membership(user=user, institution=uni, role="student")
    review_membership(actor=staff, institution=uni, membership_id=membership.pk, approve=True)
    assert titles(auth_client(user)) == ["Your membership of Example University was verified."]
