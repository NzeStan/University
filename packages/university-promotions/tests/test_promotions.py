"""Promotions: campaigns, payment, review, delivery tokens, frequency caps, budgets and reports."""

from __future__ import annotations

import datetime as dt

import pytest
from django.core.cache import cache
from django.test import override_settings
from django.utils import timezone

from tests.content.apps import ITEMS
from university.core.payables import get_payable_adapter
from university.core.testing import create_user
from university.permissions.services import assign_role
from university.promotions.models import Campaign

pytestmark = pytest.mark.django_db
BASE = "/api/v1/promotions"
FREE = {"PROMOTIONS": {"REQUIRE_PAYMENT": False, "BOOSTABLE": {"test.item": "Item"}, "DAILY_FREQUENCY_CAP": 2}}
PAID = {"PROMOTIONS": {"REQUIRE_PAYMENT": True, "BOOSTABLE": {"test.item": "Item"}}}


@pytest.fixture(autouse=True)
def _clean():
    ITEMS.clear()
    cache.clear()
    yield
    ITEMS.clear()


def ad(**extra):
    now = timezone.now()
    return {
        "name": "Freshers promo",
        "kind": "ad",
        "headline": "Half-price textbooks",
        "body": "All first-year titles this week.",
        "destination_url": "https://books.example.com/freshers",
        "placements": ["feed"],
        "starts_at": (now - dt.timedelta(minutes=1)).isoformat(),
        "ends_at": (now + dt.timedelta(days=7)).isoformat(),
        "budget_minor": 500000,
        "currency": "NGN",
        **extra,
    }


def reviewer():
    user = create_user(handle="adsreviewer", email="adsreviewer@example.com")
    assign_role(user=user, role_key="ads_reviewer")
    return user


def launch(client, auth_client, **extra):
    created = client.post(f"{BASE}/campaigns/", ad(**extra), format="json")
    assert created.status_code == 201, created.json()
    cid = created.json()["id"]
    submitted = client.post(f"{BASE}/campaigns/{cid}/submit/").json()
    assert submitted["status"] == "in_review"
    approved = auth_client(reviewer()).post(f"{BASE}/campaigns/{cid}/review/", {"approve": True}, format="json")
    assert approved.json()["status"] == "active", approved.json()
    return cid


@override_settings(UNIVERSITY=FREE)
def test_ad_lifecycle_serve_and_track(auth_client, api_client, user):
    cid = launch(auth_client(user), auth_client)
    served = api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json()
    assert len(served) == 1 and served[0]["label"] == "Sponsored" and served[0]["creative"]["headline"]
    assert served[0]["advertiser"]["handle"] == user.handle and served[0]["content"] is None
    token = served[0]["token"]
    assert api_client.post(f"{BASE}/impressions/", {"token": token}, format="json").status_code == 204
    # Replays don't inflate counts.
    api_client.post(f"{BASE}/impressions/", {"token": token}, format="json")
    click = api_client.post(f"{BASE}/clicks/", {"token": token}, format="json").json()
    assert click["destination_url"] == "https://books.example.com/freshers"
    stats = auth_client(user).get(f"{BASE}/campaigns/{cid}/stats/").json()
    assert stats["impressions"] == 1 and stats["clicks"] == 1 and stats["click_through_rate"] == 1.0
    assert stats["daily"][0]["impressions"] == 1
    # Forged tokens are rejected.
    assert api_client.post(f"{BASE}/impressions/", {"token": token + "x"}, format="json").status_code == 400
    # Unknown placement.
    assert api_client.get(f"{BASE}/serve/", {"placement": "nowhere"}).status_code == 400


@override_settings(UNIVERSITY=FREE)
def test_frequency_cap_per_viewer(auth_client, user):
    launch(auth_client(user), auth_client)
    viewer = auth_client(create_user(handle="viewer1", email="viewer1@example.com"))
    for _ in range(2):
        item = viewer.get(f"{BASE}/serve/", {"placement": "feed"}).json()[0]
        viewer.post(f"{BASE}/impressions/", {"token": item["token"]}, format="json")
    assert viewer.get(f"{BASE}/serve/", {"placement": "feed"}).json() == []
    other = auth_client(create_user(handle="viewer2", email="viewer2@example.com"))
    assert len(other.get(f"{BASE}/serve/", {"placement": "feed"}).json()) == 1


@override_settings(UNIVERSITY=FREE)
def test_budget_completes_campaign(auth_client, api_client, user):
    cid = launch(auth_client(user), auth_client)
    campaign = Campaign.objects.get(pk=cid)
    Campaign.objects.filter(pk=cid).update(impressions=campaign.impression_cap - 1)
    token = api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json()[0]["token"]
    api_client.post(f"{BASE}/impressions/", {"token": token}, format="json")
    assert Campaign.objects.get(pk=cid).status == "completed"
    assert api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json() == []


@override_settings(UNIVERSITY=FREE)
def test_validation_and_ownership(auth_client, user):
    client = auth_client(user)
    bad = client.post(
        f"{BASE}/campaigns/", ad(destination_url="http://insecure.example.com", budget_minor=100), format="json"
    )
    assert bad.status_code == 400
    assert {"destination_url", "budget_minor"} <= set(bad.json()["error"]["details"])
    cid = client.post(f"{BASE}/campaigns/", ad(), format="json").json()["id"]
    stranger = auth_client(create_user(handle="stranger", email="stranger@example.com"))
    assert stranger.get(f"{BASE}/campaigns/{cid}/").status_code == 404
    assert stranger.patch(f"{BASE}/campaigns/{cid}/", {"name": "Mine"}, format="json").status_code == 404
    assert client.patch(f"{BASE}/campaigns/{cid}/", {"name": "Renamed"}, format="json").json()["name"] == "Renamed"
    client.post(f"{BASE}/campaigns/{cid}/submit/")
    assert client.patch(f"{BASE}/campaigns/{cid}/", {"name": "Late"}, format="json").status_code == 409


@override_settings(UNIVERSITY=FREE)
def test_boost_own_visible_content_only(auth_client, api_client, user):
    other = create_user(handle="someoneelse", email="someoneelse@example.com")
    ITEMS["mine"] = {"author": user.pk, "label": "My item"}
    ITEMS["theirs"] = {"author": other.pk, "label": "Their item"}
    client = auth_client(user)
    boost = {"kind": "boost", "content_type": "test.item", "headline": "", "destination_url": ""}
    assert client.post(f"{BASE}/campaigns/", ad(object_id="theirs", **boost), format="json").status_code == 400
    assert (
        client.post(
            f"{BASE}/campaigns/", ad(object_id="mine", content_type="social.post", kind="boost"), format="json"
        ).status_code
        == 400
    )
    launch(client, auth_client, object_id="mine", **boost)
    item = api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json()[0]
    assert item["content"] == {"type": "test.item", "id": "mine"} and item["creative"] is None
    assert api_client.post(f"{BASE}/clicks/", {"token": item["token"]}, format="json").json()["content"]["id"] == "mine"
    # Hidden from a viewer: the boost isn't served to them.
    ITEMS["mine"]["hidden_from"] = {str(other.pk)}
    assert auth_client(other).get(f"{BASE}/serve/", {"placement": "feed"}).json() == []


@override_settings(UNIVERSITY=FREE)
def test_review_rules(auth_client, user):
    client = auth_client(user)
    cid = client.post(f"{BASE}/campaigns/", ad(), format="json").json()["id"]
    client.post(f"{BASE}/campaigns/{cid}/submit/")
    assert client.post(f"{BASE}/campaigns/{cid}/review/", {"approve": True}, format="json").status_code == 403
    assign_role(user=user, role_key="ads_reviewer")
    assert client.post(f"{BASE}/campaigns/{cid}/review/", {"approve": True}, format="json").status_code == 403
    rev = auth_client(reviewer())
    assert rev.get(f"{BASE}/review-queue/").json()["count"] == 1
    rejected = rev.post(
        f"{BASE}/campaigns/{cid}/review/", {"approve": False, "note": "Misleading claim"}, format="json"
    ).json()
    assert rejected["status"] == "rejected" and rejected["review_note"] == "Misleading claim"
    assert (
        auth_client(create_user(handle="plainuser", email="plainuser@example.com"))
        .get(f"{BASE}/review-queue/")
        .status_code
        == 403
    )


@override_settings(UNIVERSITY=FREE)
def test_pause_and_resume(auth_client, api_client, user):
    client = auth_client(user)
    cid = launch(client, auth_client)
    assert client.post(f"{BASE}/campaigns/{cid}/pause/").json()["status"] == "paused"
    assert api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json() == []
    assert client.post(f"{BASE}/campaigns/{cid}/resume/").json()["status"] == "active"
    assert len(api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json()) == 1


@override_settings(UNIVERSITY=PAID)
def test_payment_gate_and_refund_on_rejection(auth_client, user):
    from university.core.events import event_bus

    client = auth_client(user)
    cid = client.post(f"{BASE}/campaigns/", ad(), format="json").json()["id"]
    assert client.post(f"{BASE}/campaigns/{cid}/submit/").json()["status"] == "pending_payment"
    adapter = get_payable_adapter("promotions.campaign")
    payable = adapter.resolve(cid, user)
    assert payable.amount_minor == 500000 and payable.payee_id is None and payable.platform_fee_minor == 500000
    with pytest.raises(Exception):
        adapter.resolve(cid, create_user(handle="notpayer", email="notpayer@example.com"))
    adapter.on_paid(cid, reference="ref_1", amount_minor=500000, currency="NGN")
    assert Campaign.objects.get(pk=cid).status == "in_review"
    seen = []
    event_bus.subscribe("payments.refund.requested", seen.append)
    try:
        auth_client(reviewer()).post(f"{BASE}/campaigns/{cid}/review/", {"approve": False, "note": "No"}, format="json")
    finally:
        event_bus.unsubscribe("payments.refund.requested", seen.append)
    assert seen and Campaign.objects.get(pk=cid).payment_reference == ""


@override_settings(UNIVERSITY=FREE)
def test_reports_hide_running_ad(auth_client, api_client, user):
    from university.core.registry import registry

    cid = launch(auth_client(user), auth_client)
    adapter = registry.content_adapters.get("promotions.campaign")
    assert adapter.moderatable and adapter.can_view(None, cid)
    adapter.hide(cid, reason="scam")
    assert api_client.get(f"{BASE}/serve/", {"placement": "feed"}).json() == []
    assert not adapter.can_view(None, cid) and adapter.can_view(user, cid)


@override_settings(UNIVERSITY=FREE)
def test_export_and_purge(auth_client, user):
    from university.promotions.integrations import export_data, purge

    auth_client(user).post(f"{BASE}/campaigns/", ad(), format="json")
    assert export_data(user)["promotions"]["campaigns"][0]["name"] == "Freshers promo"
    purge(user.pk)
    assert not Campaign.objects.exists()


def test_options_public(api_client):
    body = api_client.get(f"{BASE}/options/").json()
    assert "feed" in body["placements"] and body["require_payment"] is True


@override_settings(UNIVERSITY=FREE)
def test_ad_free_entitlement_hides_ads_not_boosts(auth_client, user):
    from university.core.hooks import Hook, hooks

    launch(auth_client(user), auth_client)
    premium = create_user(handle="premium", email="premium@example.com")

    def grant(u):
        return ["premium.ad_free"] if u.pk == premium.pk else []

    hooks.register(Hook.USER_ENTITLEMENTS, grant)
    try:
        assert auth_client(premium).get(f"{BASE}/serve/", {"placement": "feed"}).json() == []
        assert (
            len(
                auth_client(create_user(handle="regular", email="regular@example.com"))
                .get(f"{BASE}/serve/", {"placement": "feed"})
                .json()
            )
            == 1
        )
    finally:
        hooks.unregister(Hook.USER_ENTITLEMENTS, grant)
