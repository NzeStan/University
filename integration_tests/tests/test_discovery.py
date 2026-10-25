"""Analytics, trending and search composed with social, community and institution (end to end)."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.analytics.models import MetricDaily
from university.community import services as community_services
from university.core.testing import create_user
from university.institution.models import Institution, InstitutionMembership, InstitutionType
from university.institution.services import request_membership
from university.permissions.scopes import Scope
from university.permissions.services import assign_role
from university.trending.services import compute_trending

pytestmark = pytest.mark.django_db


def post(client, body, **extra):
    response = client.post("/api/v1/social/posts/", {"body": body, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def crowd(n, prefix="fan"):
    return [create_user(f"{prefix}{i}@example.com", handle=f"{prefix}{i}") for i in range(n)]


@pytest.fixture
def uni(db):
    return Institution.objects.create(
        name="Example University",
        short_name="EXU",
        slug="exu",
        country="NG",
        type=InstitutionType.objects.get(key="university"),
    )


def verified(user, uni):
    membership = request_membership(user=user, institution=uni, role="student")
    InstitutionMembership.objects.filter(pk=membership.pk).update(status="verified")
    type(user).objects.filter(pk=user.pk).update(created_at=timezone.now() - dt.timedelta(days=30))
    user.refresh_from_db()


# ------------------------------------------------------------------ search
def test_search_finds_public_posts_and_respects_audiences(auth_client, api_client, user, other_user, uni):
    verified(user, uni)
    post(auth_client(user), "Exam timetable for 300 level is out")
    post(auth_client(user), "EXU exam venue changed", visibility="institution", audience_id=str(uni.pk))
    public = [r["title"] for r in api_client.get("/api/v1/search/", {"q": "exam"}).json()]
    assert public == ["Exam timetable for 300 level is out"]
    assert len(auth_client(other_user).get("/api/v1/search/", {"q": "exam"}).json()) == 1
    verified(other_user, uni)
    titles = {r["title"] for r in auth_client(other_user).get("/api/v1/search/", {"q": "exam"}).json()}
    assert titles == {"Exam timetable for 300 level is out", "EXU exam venue changed"}


@pytest.mark.security
def test_private_communities_and_blocks_never_leak_through_search(auth_client, api_client, user, other_user):
    club = community_services.create_community(creator=user, data={"name": "Secret Society", "privacy": "private"})
    post(auth_client(user), "Secret society meeting tonight", visibility="community", audience_id=str(club.pk))
    assert api_client.get("/api/v1/search/", {"q": "secret"}).json() == []
    assert auth_client(other_user).get("/api/v1/search/", {"q": "secret"}).json() == []
    assert [r["content_type"] for r in api_client.get("/api/v1/search/", {"q": "Secret Society"}).json()] == []
    post(auth_client(user), "Public notice about tutorials")
    auth_client(user).post(f"/api/v1/social/users/{other_user.pk}/block/")
    assert auth_client(other_user).get("/api/v1/search/", {"q": "tutorials"}).json() == []
    assert auth_client(other_user).get("/api/v1/search/people/", {"q": "ada"}).json() == []


def test_moderation_removal_drops_search_results(auth_client, api_client, user, other_user):
    from university.moderation.models import ModerationCase

    created = post(auth_client(user), "Buy cheap essays here")
    assert len(api_client.get("/api/v1/search/", {"q": "essays"}).json()) == 1
    moderator = create_user("mod@example.com", handle="modx")
    assign_role(user=moderator, role_key="platform_moderator")
    auth_client(other_user).post(
        "/api/v1/moderation/reports/",
        {"content_type": "social.post", "object_id": created["id"], "reason": "spam"},
        format="json",
    )
    case = ModerationCase.objects.get()
    hidden = auth_client(moderator).post(
        f"/api/v1/moderation/cases/{case.pk}/actions/", {"action": "hide", "reason": "Spam"}, format="json"
    )
    assert hidden.status_code == 201, hidden.json()
    assert api_client.get("/api/v1/search/", {"q": "essays"}).json() == []


# ---------------------------------------------------------------- trending
def test_trending_ranks_real_engagement_and_feeds_use_it(auth_client, api_client, user, other_user):
    quiet = post(auth_client(user), "Quiet post")
    lively = post(auth_client(other_user), "Lively post")
    for fan in crowd(4):
        client = auth_client(fan)
        client.post(f"/api/v1/social/posts/{lively['id']}/reaction/", {"kind": "like"}, format="json")
        client.post(f"/api/v1/social/posts/{lively['id']}/comments/", {"body": "Great!"}, format="json")
    auth_client(crowd(1, prefix="lone")[0]).post(
        f"/api/v1/social/posts/{quiet['id']}/reaction/", {"kind": "like"}, format="json"
    )
    assert compute_trending() >= 1
    items = api_client.get("/api/v1/trending/", {"type": "social.post"}).json()
    assert items[0]["object_id"] == lively["id"]
    assert all(i["object_id"] != quiet["id"] for i in items)  # One like from one person isn't trending.
    feed = api_client.get("/api/v1/social/feeds/trending/").json()["results"]
    assert feed[0]["id"] == lively["id"]


@pytest.mark.security
def test_trending_lists_hide_what_the_viewer_cannot_see(auth_client, api_client, user, uni):
    verified(user, uni)
    scoped = post(auth_client(user), "Campus-only buzz", visibility="institution", audience_id=str(uni.pk))
    fans = crowd(3)
    for fan in fans:
        verified(fan, uni)
        auth_client(fan).post(f"/api/v1/social/posts/{scoped['id']}/reaction/", {"kind": "like"}, format="json")
    compute_trending()
    assert api_client.get("/api/v1/trending/").json() == []
    member_view = (
        auth_client(fans[0]).get("/api/v1/trending/", {"scope_type": "institution", "scope_id": str(uni.pk)}).json()
    )
    assert [i["object_id"] for i in member_view] == [scoped["id"]]


# --------------------------------------------------------------- analytics
def test_institution_analytics_from_real_activity(auth_client, user, other_user, uni):
    verified(user, uni)
    for i in range(6):
        post(auth_client(user), f"Campus update {i}", visibility="institution", audience_id=str(uni.pk))
    viewed = post(auth_client(user), "Public post")
    auth_client(other_user).post(
        "/api/v1/analytics/views/", {"content_type": "social.post", "object_id": viewed["id"]}, format="json"
    )
    assert MetricDaily.objects.get(metric="views.social.post", scope_type="").count == 1
    dean = create_user("dean@example.com", handle="dean")
    assign_role(user=dean, role_key="analytics_viewer", scope=Scope("institution", str(uni.pk)))
    report = auth_client(dean).get(f"/api/v1/analytics/scopes/institution/{uni.pk}/").json()
    totals = {m["metric"]: m["total"] for m in report["metrics"]}
    assert totals["social.post.created"] == 6
    assert "user.created" not in totals or totals["user.created"] is None  # Small numbers are suppressed.
    assert auth_client(dean).get("/api/v1/analytics/overview/").status_code == 403
