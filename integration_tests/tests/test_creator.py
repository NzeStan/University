"""Creator composed with social, notifications, moderation and community."""

from __future__ import annotations

import pytest

from university.community import services as community_services
from university.core.testing import create_user
from university.creator.services import sync_categories
from university.moderation.models import ModerationCase
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db

ME = "/api/v1/me/creator/"


@pytest.fixture(autouse=True)
def _categories(db):
    sync_categories()


def titles(client):
    return [n["title"] for n in client.get("/api/v1/notifications/").json()["results"]]


def become_creator(client):
    response = client.post(ME, {"headline": "Campus creator", "categories": ["comedy"]}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def test_social_activity_feeds_creator_analytics(auth_client, user, other_user):
    become_creator(auth_client(user))
    grace = auth_client(other_user)
    grace.post(f"/api/v1/social/users/{user.pk}/follow/")
    post = auth_client(user).post("/api/v1/social/posts/", {"body": "New skit tonight!"}, format="json").json()
    grace.post(f"/api/v1/social/posts/{post['id']}/reaction/", {"kind": "like"}, format="json")
    grace.post(f"/api/v1/social/posts/{post['id']}/comments/", {"body": "Can't wait"}, format="json")
    grace.delete(f"/api/v1/social/users/{user.pk}/follow/")
    totals = {m["metric"]: m["total"] for m in auth_client(user).get(f"{ME}analytics/").json()["metrics"]}
    assert totals["followers_gained"] == 1 and totals["followers_lost"] == 1
    assert totals["posts_published"] == 1 and totals["reactions_received"] == 1 and totals["comments_received"] == 1


def test_media_kit_shows_platform_followers(auth_client, user, other_user):
    become_creator(auth_client(user))
    auth_client(other_user).post(f"/api/v1/social/users/{user.pk}/follow/")
    auth_client(user).patch(f"{ME}media-kit/", {"visibility": "public"}, format="json")
    kit = auth_client(other_user).get(f"/api/v1/creators/{user.handle}/media-kit/").json()
    assert kit["platform_stats"]["platform_followers"] == 1


@pytest.mark.security
def test_blocks_hide_creators_and_stop_invitations(auth_client, user, other_user):
    profile = become_creator(auth_client(user))
    auth_client(user).post(f"/api/v1/social/users/{other_user.pk}/block/")
    assert auth_client(other_user).get(f"/api/v1/creators/{user.handle}/").status_code == 404
    assert auth_client(other_user).get("/api/v1/creators/").json()["results"] == []
    campaign = (
        auth_client(other_user)
        .post(
            "/api/v1/campaigns/", {"brand_name": "Shop", "title": "Promo", "brief": "Promote our shop."}, format="json"
        )
        .json()
    )
    invite = auth_client(other_user).post(
        f"/api/v1/campaigns/{campaign['id']}/invitations/", {"profile_id": profile["id"]}, format="json"
    )
    assert invite.status_code == 404


def test_sponsorship_notifications(auth_client, user, other_user):
    brand, creator = auth_client(user), auth_client(other_user)
    campaign = brand.post(
        "/api/v1/campaigns/",
        {"brand_name": "Campus Bank", "title": "Freshers week", "brief": "Promote it."},
        format="json",
    ).json()
    brand.post(f"/api/v1/campaigns/{campaign['id']}/publish/")
    become_creator(creator)
    participation = creator.post(
        f"/api/v1/campaigns/{campaign['id']}/apply/", {"pitch": "My skits reach every hostel."}, format="json"
    ).json()
    assert titles(brand) == ["A creator applied to Freshers week."]
    brand.post(f"/api/v1/participations/{participation['id']}/decision/", {"action": "accept"}, format="json")
    assert titles(creator) == ["You're in! You've been accepted for Freshers week."]
    deliverable = brand.post(
        f"/api/v1/participations/{participation['id']}/deliverables/", {"title": "Reel"}, format="json"
    ).json()
    creator.post(
        f"/api/v1/deliverables/{deliverable['id']}/submit/",
        {"url": "https://instagram.com/p/1", "disclosure_confirmed": True},
        format="json",
    )
    assert titles(brand)[0] == "A deliverable was submitted for Freshers week."
    brand.post(f"/api/v1/deliverables/{deliverable['id']}/review/", {"approve": True}, format="json")
    assert titles(creator)[0] == "Your deliverable for Freshers week was approved."


def test_verification_notifications_and_badge(auth_client, api_client, user):
    reviewer = create_user("reviewer@example.com", handle="reviewer")
    assign_role(user=reviewer, role_key="creator_reviewer")
    become_creator(auth_client(user))
    request = (
        auth_client(user)
        .post(f"{ME}verification/", {"statement": "I make weekly comedy skits for students."}, format="json")
        .json()
    )
    auth_client(reviewer).post(f"/api/v1/creator/verification-requests/{request['id']}/approve/")
    assert titles(auth_client(user))[0] == "Your creator profile is now verified."
    profile = api_client.get(f"/api/v1/users/by-handle/{user.handle}/").json()
    assert "'creator': {" in str(profile) and "'verified': True" in str(profile)


@pytest.mark.security
def test_campaign_reports_go_to_the_sponsor(auth_client, user, other_user):
    club = community_services.create_community(creator=user, data={"name": "Robotics"})
    assign_role(user=user, role_key="campaign_manager", scope=Scope("community", str(club.pk)))
    campaign = (
        auth_client(user)
        .post(
            "/api/v1/campaigns/",
            {
                "brand_name": "Robotics Club",
                "title": "Sponsor our bot",
                "brief": "Help us.",
                "sponsor_type": "community",
                "sponsor_id": str(club.pk),
            },
            format="json",
        )
        .json()
    )
    auth_client(user).post(f"/api/v1/campaigns/{campaign['id']}/publish/")
    report = auth_client(other_user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "creator.campaign", "object_id": campaign["id"], "reason": "spam"},
        format="json",
    )
    assert report.status_code == 201, report.json()
    case = ModerationCase.objects.get()
    assert (case.scope_type, case.scope_id) == ("community", str(club.pk))
