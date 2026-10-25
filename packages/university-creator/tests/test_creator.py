from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from tests import fakes
from university.core.events import publish
from university.core.testing import create_user
from university.creator import services
from university.creator.models import Campaign, CreatorDailyStat, LinkedAccount, Participation
from university.creator.providers import ExternalProfile
from university.permissions.scopes import Scope
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
ME = "/api/v1/me/creator/"
INST = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _providers(settings):
    fakes.PROFILES.clear()
    settings.UNIVERSITY = {
        "CREATOR": {"PROVIDERS": {"faketube": {"label": "FakeTube", "class": "tests.fakes.FakeProvider"}}}
    }
    services.sync_categories()
    yield
    fakes.PROFILES.clear()


def become_creator(client, **data):
    payload = {
        "headline": "Campus comedian",
        "bio": "Skits about hostel life",
        "categories": ["comedy"],
        "country": "ng",
        **data,
    }
    response = client.post(ME, payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


@pytest.fixture
def reviewer(db):
    person = create_user("reviewer@example.com", handle="reviewer")
    assign_role(user=person, role_key="creator_reviewer")
    return person


def verified_account(client, handle="adaskits", followers=12000):
    account = client.post(f"{ME}linked-accounts/", {"provider": "faketube", "handle": handle}, format="json").json()
    fakes.PROFILES[handle] = ExternalProfile(
        external_id=f"ext-{handle}", handle=handle, follower_count=followers, bio=f"Skits! {account['challenge']}"
    )
    response = client.post(f"{ME}linked-accounts/{account['id']}/verify/")
    assert response.status_code == 200, response.json()
    return response.json()


# ----------------------------------------------------------------- profiles
def test_profile_lifecycle_and_privacy(auth_client, api_client, user, other_user):
    me = auth_client(user)
    profile = become_creator(me)
    assert profile["country"] == "NG" and [c["key"] for c in profile["categories"]] == ["comedy"]
    assert me.post(ME, {"headline": "again"}, format="json").status_code == 409
    assert me.patch(ME, {"categories": ["comedy", "music", "tech", "food"]}, format="json").status_code == 400
    assert me.patch(ME, {"categories": ["nope"]}, format="json").status_code == 400
    assert api_client.get(f"/api/v1/creators/{user.handle}/").json()["headline"] == "Campus comedian"
    assert [c["user"]["handle"] for c in api_client.get("/api/v1/creators/").json()["results"]] == ["ada"]
    # The account's own privacy settings apply.
    from university.users.services.preferences import get_privacy_settings

    privacy = get_privacy_settings(user)
    privacy.profile_visibility = "private"
    privacy.save()
    assert api_client.get(f"/api/v1/creators/{user.handle}/").status_code == 404
    assert api_client.get("/api/v1/creators/").json()["results"] == []
    assert me.get(ME).status_code == 200
    privacy.profile_visibility = "public"
    privacy.save()
    me.patch(ME, {"status": "paused"}, format="json")
    assert auth_client(other_user).get(f"/api/v1/creators/{user.handle}/").status_code == 404
    # The badge appears on the public account profile.
    me.patch(ME, {"status": "active"}, format="json")
    from university.core.hooks import Hook, hooks

    assert hooks.collect(Hook.USER_PUBLIC_PROFILE, user, None)["creator"]["verified"] is False


def test_discovery_filters(auth_client, api_client, user, other_user):
    become_creator(auth_client(user))
    become_creator(auth_client(other_user), headline="Afrobeats producer", categories=["music"], country="gh")
    verified_account(auth_client(other_user), "gracebeats", 50000)
    results = lambda **q: [c["user"]["handle"] for c in api_client.get("/api/v1/creators/", q).json()["results"]]  # noqa: E731
    assert results() == ["grace", "ada"]  # By verified reach.
    assert results(category="music") == ["grace"]
    assert results(country="NG") == ["ada"]
    assert results(min_reach="10000") == ["grace"]
    assert results(q="afrobeats") == ["grace"]


# ----------------------------------------------------------- verification
@pytest.mark.security
def test_verification_review(auth_client, user, other_user, reviewer):
    me = auth_client(user)
    profile = become_creator(me)
    assert me.post(f"{ME}verification/", {"statement": "too short"}, format="json").status_code == 400
    req = me.post(
        f"{ME}verification/",
        {"statement": "I make weekly comedy skits for 50k students.", "links": ["https://news.example.com/ada"]},
        format="json",
    ).json()
    assert (
        me.post(f"{ME}verification/", {"statement": "I make weekly comedy skits again."}, format="json").status_code
        == 409
    )
    assert auth_client(other_user).get("/api/v1/creator/verification-requests/").status_code == 403
    queue = auth_client(reviewer).get("/api/v1/creator/verification-requests/").json()["results"]
    assert [r["id"] for r in queue] == [req["id"]]
    # Reviewers can't approve themselves.
    become_creator(auth_client(reviewer))
    own = (
        auth_client(reviewer)
        .post(f"{ME}verification/", {"statement": "Reviewer with a creator page too."}, format="json")
        .json()
    )
    assert auth_client(reviewer).post(f"/api/v1/creator/verification-requests/{own['id']}/approve/").status_code == 403
    approved = auth_client(reviewer).post(
        f"/api/v1/creator/verification-requests/{req['id']}/approve/", {"reason": "Notable"}, format="json"
    )
    assert approved.json()["status"] == "approved"
    assert me.get(ME).json()["is_verified"] is True
    revoke = f"/api/v1/creators/{profile['id']}/revoke-verification/"
    assert auth_client(reviewer).post(revoke, {"reason": ""}, format="json").status_code == 400
    assert (
        auth_client(reviewer).post(revoke, {"reason": "Bought followers"}, format="json").json()["verification_status"]
        == "revoked"
    )


# --------------------------------------------------------- linked accounts
@pytest.mark.security
def test_linked_account_ownership_and_reach(auth_client, api_client, user, other_user):
    me = auth_client(user)
    become_creator(me)
    account = me.post(
        f"{ME}linked-accounts/",
        {"provider": "faketube", "handle": "@AdaSkits", "follower_count": 999999},
        format="json",
    ).json()
    assert (
        account["handle"] == "AdaSkits"
        and account["ownership"] == "unverified"
        and account["challenge"].startswith("UNIV-")
    )
    assert me.post(f"{ME}linked-accounts/", {"provider": "myspace", "handle": "ada"}, format="json").status_code == 400
    assert (
        me.post(f"{ME}linked-accounts/", {"provider": "faketube", "handle": "not a handle!"}, format="json").status_code
        == 400
    )
    me.post(
        f"{ME}linked-accounts/", {"provider": "faketube", "handle": "adaclips", "follower_count": 50000}, format="json"
    )
    assert me.get(ME).json()["verified_reach"] == 0  # Self-reported counts don't count.
    fakes.PROFILES["adaskits"] = ExternalProfile(external_id="1", handle="AdaSkits", follower_count=12000, bio="hello")
    missing = me.post(f"{ME}linked-accounts/{account['id']}/verify/")
    assert missing.json()["error"]["code"] == "challenge_not_found"
    fakes.PROFILES["adaskits"] = ExternalProfile(
        external_id="1", handle="AdaSkits", follower_count=12000, bio=f"skits {account['challenge']}"
    )
    verified = me.post(f"{ME}linked-accounts/{account['id']}/verify/").json()
    assert (
        verified["ownership"] == "verified"
        and verified["follower_count"] == 12000
        and verified["count_source"] == "provider"
    )
    assert me.get(ME).json()["verified_reach"] == 12000
    assert (
        me.patch(f"{ME}linked-accounts/{account['id']}/", {"follower_count": 5}, format="json").json()["error"]["code"]
        == "count_confirmed"
    )
    # Someone else can't claim the same verified account.
    become_creator(auth_client(other_user))
    impostor = (
        auth_client(other_user)
        .post(f"{ME}linked-accounts/", {"provider": "faketube", "handle": "adaskits"}, format="json")
        .json()
    )
    fakes.PROFILES["adaskits"] = ExternalProfile(external_id="1", handle="AdaSkits", bio=f"{impostor['challenge']}")
    claim = auth_client(other_user).post(f"{ME}linked-accounts/{impostor['id']}/verify/")
    assert claim.status_code == 409 and claim.json()["error"]["code"] == "account_claimed"
    # The public sees accounts but not challenge codes.
    public = api_client.get(f"/api/v1/creators/{user.handle}/").json()["linked_accounts"]
    assert public[0]["handle"] == "AdaSkits" and "challenge" not in public[0]
    me.delete(f"{ME}linked-accounts/{account['id']}/")
    assert me.get(ME).json()["verified_reach"] == 0


def test_manual_platforms_need_a_reviewer(settings, auth_client, user, reviewer):
    settings.UNIVERSITY = {
        "CREATOR": {"PROVIDERS": {"tiktok": {"label": "TikTok", "url": "https://www.tiktok.com/@{handle}"}}}
    }
    me = auth_client(user)
    become_creator(me)
    account = me.post(
        f"{ME}linked-accounts/", {"provider": "tiktok", "handle": "ada.skits", "follower_count": 3000}, format="json"
    ).json()
    assert account["ownership"] == "pending_review" and account["url"] == "https://www.tiktok.com/@ada.skits"
    assert me.post(f"{ME}linked-accounts/{account['id']}/verify/").json()["error"]["code"] == "manual_review"
    queue = auth_client(reviewer).get("/api/v1/creator/linked-accounts/").json()["results"]
    assert [a["id"] for a in queue] == [account["id"]]
    confirmed = auth_client(reviewer).post(
        f"/api/v1/creator/linked-accounts/{account['id']}/confirm/", {"follower_count": 2800}, format="json"
    )
    assert confirmed.json()["count_source"] == "reviewer"
    assert me.get(ME).json()["verified_reach"] == 2800
    providers = auth_client(user).get("/api/v1/creator-providers/").json()
    assert {"key": "tiktok", "label": "TikTok", "automatic_verification": False} in providers
    assert "boomplay" in {p["key"] for p in providers}  # Defaults stay unless set to None.


def test_sync_refreshes_counts_and_snapshots(auth_client, user):
    from university.creator.models import LinkedAccountSnapshot

    me = auth_client(user)
    become_creator(me)
    account = verified_account(me, "adaskits", 1000)
    fakes.PROFILES["adaskits"] = ExternalProfile(external_id="ext", handle="adaskits", follower_count=1500, bio="")
    assert services.sync_linked_accounts() == 0  # Synced recently.
    LinkedAccount.objects.update(last_synced_at=timezone.now() - dt.timedelta(days=2))
    assert services.sync_linked_accounts() == 1
    assert LinkedAccount.objects.get().follower_count == 1500
    assert LinkedAccountSnapshot.objects.get(account_id=account["id"]).follower_count == 1500
    assert me.get(ME).json()["verified_reach"] == 1500


# --------------------------------------------------------------- media kit
@pytest.mark.security
def test_media_kit_visibility_and_validation(auth_client, api_client, user):
    me = auth_client(user)
    become_creator(me)
    url = f"/api/v1/creators/{user.handle}/media-kit/"
    assert api_client.get(url).status_code == 404  # Private by default.
    bad = me.patch(f"{ME}media-kit/", {"audience": {"age": {"18-24": 80, "25-34": 40}}}, format="json")
    assert bad.status_code == 400
    assert (
        me.patch(f"{ME}media-kit/", {"rates": [{"deliverable": "Reel", "price_minor": -5}]}, format="json").status_code
        == 400
    )
    assert (
        me.patch(
            f"{ME}media-kit/", {"highlights": [{"title": "x", "url": "http://insecure"}]}, format="json"
        ).status_code
        == 400
    )
    kit = me.patch(
        f"{ME}media-kit/",
        {
            "visibility": "unlisted",
            "summary": "Campus comedy with 12k engaged students",
            "audience": {"age": {"18-24": 70, "25-34": 25}, "countries": {"NG": 85, "GH": 10}},
            "rates": [{"deliverable": "Instagram reel", "price_minor": 5000000}],
            "highlights": [
                {"title": "Freshers week", "brand": "Campus Bank", "url": "https://example.com/x", "year": "2025"}
            ],
        },
        format="json",
    ).json()
    assert kit["rates"][0]["currency"] == "NGN"
    assert api_client.get(url).status_code == 404
    assert api_client.get(url, {"token": "wrong"}).status_code == 404
    shared = api_client.get(url, {"token": kit["share_token"]}).json()
    assert shared["summary"].startswith("Campus comedy") and "share_token" not in shared
    assert shared["platform_stats"]["verified_reach"] == 0
    rotated = me.post(f"{ME}media-kit/rotate-link/").json()
    assert api_client.get(url, {"token": kit["share_token"]}).status_code == 404
    assert api_client.get(url, {"token": rotated["share_token"]}).status_code == 200
    me.patch(f"{ME}media-kit/", {"visibility": "public"}, format="json")
    assert api_client.get(url).status_code == 200


# --------------------------------------------------------------- analytics
def test_analytics_are_daily_aggregates(auth_client, api_client, user, other_user, third_user):
    me = auth_client(user)
    become_creator(me)
    for follower in (other_user, third_user):
        publish("social.follow.created", {"follower_id": follower.pk, "followee_id": user.pk}, actor=follower)
    publish("social.follow.removed", {"follower_id": other_user.pk, "followee_id": user.pk}, actor=other_user)
    publish("social.post.reacted", {"post_id": 1, "post_author_id": user.pk, "user_id": other_user.pk, "kind": "like"})
    publish(
        "social.post.reacted", {"post_id": 1, "post_author_id": user.pk, "user_id": user.pk, "kind": "like"}
    )  # Self.
    publish(
        "social.comment.created", {"comment_id": 1, "post_id": 1, "author_id": third_user.pk, "post_author_id": user.pk}
    )
    # Non-creators aren't tracked at all.
    publish("social.follow.created", {"follower_id": user.pk, "followee_id": other_user.pk}, actor=user)
    assert not CreatorDailyStat.objects.exclude(profile__user=user).exists()
    # Profile views: once per viewer per window, never the creator.
    for _ in range(3):
        auth_client(other_user).get(f"/api/v1/creators/{user.handle}/")
    me.get(f"/api/v1/creators/{user.handle}/")
    api_client.get(f"/api/v1/creators/{user.handle}/")
    report = me.get(f"{ME}analytics/").json()
    totals = {m["metric"]: m["total"] for m in report["metrics"]}
    assert totals["followers_gained"] == 2 and totals["followers_lost"] == 1 and report["net_followers"] == 1
    assert totals["reactions_received"] == 1 and totals["comments_received"] == 1
    assert totals["profile_views"] == 2
    assert len(report["metrics"][0]["series"]) == 30
    only = me.get(f"{ME}analytics/", {"metrics": "profile_views", "from": "2026-01-01", "to": "2026-01-07"}).json()
    assert [m["metric"] for m in only["metrics"]] == ["profile_views"] and len(only["metrics"][0]["series"]) == 7
    assert me.get(f"{ME}analytics/", {"from": "2020-01-01", "to": "2026-01-01"}).status_code == 400
    # Analytics are private to the creator (and support staff with creator.analytics.view).
    profile_id = me.get(ME).json()["id"]
    assert auth_client(other_user).get(f"/api/v1/creators/{profile_id}/analytics/").status_code == 403
    assert "viewer" not in str(CreatorDailyStat.objects.values()).lower()


# --------------------------------------------------------------- campaigns
def campaign(client, **data):
    payload = {
        "brand_name": "Campus Bank",
        "title": "Freshers week",
        "brief": "Promote our student account.",
        "categories": ["comedy"],
        "slots": 1,
        "budget_minor": 20000000,
        **data,
    }
    response = client.post("/api/v1/campaigns/", payload, format="json")
    assert response.status_code == 201, response.json()
    created = response.json()
    assert client.post(f"/api/v1/campaigns/{created['id']}/publish/").status_code == 200
    return created


def test_application_flow_with_slots(auth_client, api_client, user, other_user, third_user):
    brand = auth_client(user)
    c = campaign(brand)
    assert [x["title"] for x in api_client.get("/api/v1/campaigns/").json()["results"]] == ["Freshers week"]
    grace, ngozi = auth_client(other_user), auth_client(third_user)
    assert (
        grace.post(f"/api/v1/campaigns/{c['id']}/apply/", {"pitch": "I'd love to"}, format="json").status_code == 404
    )  # No profile.
    become_creator(grace)
    become_creator(ngozi)
    a = grace.post(
        f"/api/v1/campaigns/{c['id']}/apply/",
        {"pitch": "My skits reach every hostel.", "proposed_fee_minor": 10000000},
        format="json",
    ).json()
    b = ngozi.post(
        f"/api/v1/campaigns/{c['id']}/apply/", {"pitch": "I run the biggest campus page."}, format="json"
    ).json()
    assert (
        grace.post(f"/api/v1/campaigns/{c['id']}/apply/", {"pitch": "Again please."}, format="json").status_code == 409
    )
    assert grace.get(f"/api/v1/campaigns/{c['id']}/participations/").status_code == 404
    listed = brand.get(f"/api/v1/campaigns/{c['id']}/participations/").json()["results"]
    assert {p["creator"]["user"]["handle"] for p in listed} == {"grace", "ngozi"}
    decide = lambda client, pid, **d: client.post(f"/api/v1/participations/{pid}/decision/", d, format="json")  # noqa: E731
    assert decide(brand, a["id"], action="shortlist").json()["status"] == "shortlisted"
    accepted = decide(brand, a["id"], action="accept").json()
    assert accepted["status"] == "accepted" and accepted["agreed_fee_minor"] == 10000000
    full = decide(brand, b["id"], action="accept")
    assert full.status_code == 409 and full.json()["error"]["code"] == "slots_full"
    assert decide(ngozi, b["id"], action="withdraw").json()["status"] == "withdrawn"
    assert decide(grace, a["id"], action="shortlist").status_code == 409  # Creators can't act as the brand.
    # The creator cancels: the slot frees up.
    assert decide(grace, a["id"], action="cancel").json()["status"] == "cancelled"
    assert Campaign.objects.get(pk=c["id"]).accepted_count == 0


@pytest.mark.security
def test_requirements_invitations_and_deliverables(auth_client, user, other_user, third_user):
    brand = auth_client(user)
    c = campaign(brand, verified_only=True, visibility="invite_only", slots=None)
    grace = auth_client(other_user)
    profile = become_creator(grace)
    invite = brand.post(f"/api/v1/campaigns/{c['id']}/invitations/", {"profile_id": profile["id"]}, format="json")
    assert invite.json()["error"]["code"] == "verified_only"
    from university.creator.models import CreatorProfile

    CreatorProfile.objects.filter(pk=profile["id"]).update(verification_status="verified")
    p = brand.post(
        f"/api/v1/campaigns/{c['id']}/invitations/",
        {"profile_id": profile["id"], "note": "Love your work"},
        format="json",
    ).json()
    assert p["status"] == "invited"
    # Invite-only campaigns are visible to participants, not the public.
    assert auth_client(third_user).get(f"/api/v1/campaigns/{c['id']}/").status_code == 404
    assert grace.get(f"/api/v1/campaigns/{c['id']}/").json()["viewer"]["participation_status"] == "invited"
    decide = lambda client, **d: client.post(f"/api/v1/participations/{p['id']}/decision/", d, format="json")  # noqa: E731
    assert decide(grace, action="accept").json()["status"] == "accepted"
    url = f"/api/v1/participations/{p['id']}/deliverables/"
    assert grace.post(url, {"title": "Reel"}, format="json").status_code == 403
    d = brand.post(
        url, {"title": "Instagram reel", "due_at": (timezone.now() + dt.timedelta(days=7)).isoformat()}, format="json"
    ).json()
    submit = f"/api/v1/deliverables/{d['id']}/submit/"
    no_ad = grace.post(submit, {"url": "https://instagram.com/p/1"}, format="json")
    assert no_ad.json()["error"]["code"] == "disclosure_required"
    assert (
        grace.post(submit, {"url": "https://instagram.com/p/1", "disclosure_confirmed": True}, format="json").json()[
            "status"
        ]
        == "submitted"
    )
    review = f"/api/v1/deliverables/{d['id']}/review/"
    assert grace.post(review, {"approve": True}, format="json").status_code == 403
    assert decide(brand, action="complete").json()["error"]["code"] == "deliverables_pending"
    assert brand.post(review, {"approve": False}, format="json").status_code == 400
    assert (
        brand.post(review, {"approve": False, "note": "Mention the app"}, format="json").json()["status"]
        == "changes_requested"
    )
    grace.post(submit, {"url": "https://instagram.com/p/2", "disclosure_confirmed": True}, format="json")
    brand.post(review, {"approve": True}, format="json")
    assert decide(brand, action="complete").json()["status"] == "completed"
    assert auth_client(third_user).get(url).status_code == 404  # Outsiders see nothing.


def test_sponsored_campaigns_need_scope_permission(auth_client, user, other_user):
    payload = {
        "brand_name": "EXU SU",
        "title": "Elections",
        "brief": "Promote turnout.",
        "sponsor_type": "institution",
        "sponsor_id": INST,
    }
    assert auth_client(user).post("/api/v1/campaigns/", payload, format="json").status_code == 403
    assign_role(user=user, role_key="campaign_manager", scope=Scope("institution", INST))
    created = auth_client(user).post("/api/v1/campaigns/", payload, format="json").json()
    assert created["sponsor"] == {"type": "institution", "id": INST}
    # Other campaign managers of the sponsor can manage it.
    assign_role(user=other_user, role_key="campaign_manager", scope=Scope("institution", INST))
    assert (
        auth_client(other_user)
        .patch(f"/api/v1/campaigns/{created['id']}/", {"title": "Vote!"}, format="json")
        .status_code
        == 200
    )
    unverified = create_user("new@example.com", handle="newbie", verified=False)
    assert (
        auth_client(unverified)
        .post("/api/v1/campaigns/", {"brand_name": "x", "title": "x", "brief": "x"}, format="json")
        .status_code
        == 403
    )


@pytest.mark.security
def test_campaign_moderation_policy(auth_client, api_client, user, other_user):
    from university.core.content import get_moderatable_adapter

    brand = auth_client(user)
    c = campaign(brand, slots=None)
    become_creator(auth_client(other_user))
    p = (
        auth_client(other_user)
        .post(f"/api/v1/campaigns/{c['id']}/apply/", {"pitch": "Count me in, please."}, format="json")
        .json()
    )
    adapter = get_moderatable_adapter("creator.campaign")
    assert adapter.resolve(c["id"]).author_id == str(user.pk) and adapter.resolve(c["id"]).scope is None
    adapter.hide(c["id"], reason="Advance-fee scam")
    assert api_client.get(f"/api/v1/campaigns/{c['id']}/").status_code == 404
    assert api_client.get("/api/v1/campaigns/").json()["count"] == 0
    brand.post(f"/api/v1/campaigns/{c['id']}/close/")
    assert brand.post(f"/api/v1/campaigns/{c['id']}/publish/").json()["error"]["code"] == "campaign_hidden"
    adapter.remove(c["id"], reason="Scam")
    assert Participation.objects.get(pk=p["id"]).status == "cancelled"
    assert Campaign.all_objects.get(pk=c["id"]).deleted_at is not None


def test_export_purge_and_retention(auth_client, user, other_user):
    from university.core.hooks import Hook, hooks
    from university.core.retention import run_retention

    me = auth_client(user)
    become_creator(me)
    verified_account(me)
    c = campaign(auth_client(other_user), slots=1)
    p = me.post(f"/api/v1/campaigns/{c['id']}/apply/", {"pitch": "Pick me for this one."}, format="json").json()
    auth_client(other_user).post(f"/api/v1/participations/{p['id']}/decision/", {"action": "accept"}, format="json")
    exported = hooks.collect(Hook.USER_EXPORT_DATA, user)["creator_profile"]
    assert exported["linked_accounts"][0]["handle"] == "adaskits" and "challenge" not in str(exported)
    hooks.call(Hook.USER_PURGE, user.pk)
    assert not LinkedAccount.objects.exists()
    assert Campaign.objects.get(pk=c["id"]).accepted_count == 0  # The slot came back.
    publish("social.follow.created", {"follower_id": user.pk, "followee_id": other_user.pk})
    become_creator(auth_client(other_user))
    publish("social.follow.created", {"follower_id": user.pk, "followee_id": other_user.pk})
    CreatorDailyStat.objects.update(date=timezone.localdate() - dt.timedelta(days=800))
    assert run_retention(only=["creator.analytics"])["creator.analytics"] == 1


def test_youtube_provider(monkeypatch):
    from university.creator import providers

    seen = {}

    def fake_request(method, url):
        seen["url"] = url
        return {
            "items": [
                {
                    "id": "UC123",
                    "snippet": {"title": "Ada Skits", "description": "UNIV-ABC"},
                    "statistics": {"subscriberCount": "4200", "hiddenSubscriberCount": False},
                }
            ]
        }

    monkeypatch.setattr(providers, "request", fake_request)
    yt = providers.YouTubeProvider("youtube", api_key="k")
    profile = yt.fetch_profile("@adaskits")
    assert profile.external_id == "UC123" and profile.follower_count == 4200 and "UNIV-ABC" in profile.bio
    assert "forHandle=%40adaskits" in seen["url"] and profile.url == "https://www.youtube.com/@adaskits"
    monkeypatch.setattr(providers, "request", lambda method, url: {"items": []})
    assert yt.fetch_profile("ghost") is None
    with pytest.raises(ValueError):
        providers.YouTubeProvider("youtube")


def test_active_campaign_limit(settings, auth_client, user):
    settings.UNIVERSITY = {"CREATOR": {"MAX_OPEN_CAMPAIGNS_PER_USER": 1}}
    brand = auth_client(user)
    payload = {"brand_name": "Shop", "title": "One", "brief": "First campaign."}
    assert brand.post("/api/v1/campaigns/", payload, format="json").status_code == 201
    second = brand.post("/api/v1/campaigns/", {**payload, "title": "Two"}, format="json")
    assert second.status_code == 403 and second.json()["error"]["code"] == "campaign_limit_reached"
