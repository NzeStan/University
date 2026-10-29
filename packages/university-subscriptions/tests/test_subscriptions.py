"""Subscriptions: plans, paying periods, renewals, grace, expiry, refunds and entitlements."""

from __future__ import annotations

import datetime as dt

import pytest
from django.utils import timezone

from university.core.entitlements import entitlements, forget, has_entitlement
from university.core.exceptions import Conflict, NotFound
from university.core.payables import get_payable_adapter
from university.core.testing import create_user
from university.subscriptions import services
from university.subscriptions.models import Subscription

pytestmark = pytest.mark.django_db
BASE = "/api/v1/subscriptions"
PRICE = 150000


def subscribe(client, plan="plus", interval="month"):
    response = client.post(f"{BASE}/me/", {"plan": plan, "interval": interval, "currency": "NGN"}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def pay(sub_id, reference="ref-1", amount=PRICE):
    get_payable_adapter("subscriptions.period").on_paid(
        sub_id, reference=reference, amount_minor=amount, currency="NGN"
    )


def test_plans_public(api_client):
    body = api_client.get(f"{BASE}/plans/").json()
    plus = next(p for p in body if p["key"] == "plus")
    assert {"interval": "month", "currency": "NGN", "amount_minor": PRICE} in plus["prices"]
    assert {"key": "premium.ad_free", "label": "No adverts"} in plus["entitlements"]


def test_subscribe_pay_and_hold_entitlements(auth_client, user):
    client = auth_client(user)
    sub = subscribe(client)
    assert sub["status"] == "pending_payment"
    assert sub["payment_due"] == {
        "purpose": "subscriptions.period",
        "object_id": sub["id"],
        "amount_minor": PRICE,
        "currency": "NGN",
    }
    assert not has_entitlement(user, "premium.ad_free")
    payable = get_payable_adapter("subscriptions.period").resolve(sub["id"], user)
    assert payable.amount_minor == PRICE and payable.payee_id is None and payable.platform_fee_minor == PRICE
    pay(sub["id"])
    forget(user)
    assert has_entitlement(user, "premium.ad_free") and has_entitlement(user, "premium.badge")
    me = client.get(f"{BASE}/me/").json()
    assert me["subscription"]["status"] == "active" and me["subscription"]["payment_due"] is None
    assert "premium.badge" in me["entitlements"] and len(me["subscription"]["periods"]) == 1


def test_nobody_else_can_pay_and_double_payments_are_refused(auth_client, user):
    sub = subscribe(auth_client(user))
    with pytest.raises(NotFound):
        get_payable_adapter("subscriptions.period").resolve(
            sub["id"], create_user(handle="payer2", email="payer2@example.com")
        )
    pay(sub["id"])
    # Nothing due now: a second checkout can't start, and a second payment can't be applied.
    with pytest.raises(NotFound):
        get_payable_adapter("subscriptions.period").resolve(sub["id"], user)
    with pytest.raises(Conflict):
        pay(sub["id"], reference="ref-2")
    # The wrong amount is refused too (payments then refunds it).
    Subscription.objects.filter(pk=sub["id"]).update(status="pending_payment")
    with pytest.raises(Conflict):
        pay(sub["id"], reference="ref-3", amount=1)


def test_one_live_subscription_and_plan_change_before_paying(auth_client, user):
    client = auth_client(user)
    first = subscribe(client)
    changed = subscribe(client, plan="creator_pro", interval="year")
    assert changed["id"] == first["id"] and changed["plan"] == "creator_pro"
    pay(changed["id"], amount=5000000)
    assert client.post(f"{BASE}/me/", {"plan": "plus", "interval": "month"}, format="json").status_code == 409
    assert client.post(f"{BASE}/me/", {"plan": "gold", "interval": "month"}, format="json").status_code == 400


def test_renewal_window_extends_from_period_end(auth_client, user):
    sub = subscribe(auth_client(user))
    pay(sub["id"])
    obj = Subscription.objects.get(pk=sub["id"])
    end = obj.current_period_end
    assert services.amount_due(obj) is None
    Subscription.objects.filter(pk=obj.pk).update(current_period_end=timezone.now() + dt.timedelta(days=2))
    obj.refresh_from_db()
    assert services.amount_due(obj) == PRICE
    pay(sub["id"], reference="ref-renew")
    obj.refresh_from_db()
    assert obj.current_period_end > end
    assert abs((obj.current_period_end - timezone.now()) - dt.timedelta(days=32)) < dt.timedelta(minutes=1)


def test_sweep_reminds_then_grace_then_expires(auth_client, user):
    from university.core.events import event_bus

    sub = subscribe(auth_client(user))
    pay(sub["id"])
    seen = []
    event_bus.subscribe("subscriptions.*", seen.append)
    try:
        Subscription.objects.filter(pk=sub["id"]).update(current_period_end=timezone.now() + dt.timedelta(days=1))
        assert services.sweep()["reminded"] == 1
        assert services.sweep()["reminded"] == 0  # once per period
        Subscription.objects.filter(pk=sub["id"]).update(current_period_end=timezone.now() - dt.timedelta(hours=1))
        assert services.sweep()["past_due"] == 1
        forget(user)
        assert has_entitlement(user, "premium.ad_free")  # grace period
        Subscription.objects.filter(pk=sub["id"]).update(current_period_end=timezone.now() - dt.timedelta(days=4))
        assert services.sweep()["expired"] == 1
    finally:
        event_bus.unsubscribe("subscriptions.*", seen.append)
    forget(user)
    assert entitlements(user) == frozenset()
    assert [e.name for e in seen] == ["subscriptions.subscription.renewal_due", "subscriptions.subscription.expired"]


def test_lapsed_subscription_can_be_paid_in_grace(auth_client, user):
    sub = subscribe(auth_client(user))
    pay(sub["id"])
    Subscription.objects.filter(pk=sub["id"]).update(
        status="past_due", current_period_end=timezone.now() - dt.timedelta(days=1)
    )
    pay(sub["id"], reference="ref-late")
    obj = Subscription.objects.get(pk=sub["id"])
    assert obj.status == "active" and obj.current_period_end > timezone.now() + dt.timedelta(days=29)


def test_cancel_at_period_end(auth_client, user):
    client = auth_client(user)
    sub = subscribe(client)
    assert client.post(f"{BASE}/me/cancel/", {}, format="json").status_code == 404
    pay(sub["id"])
    assert client.post(f"{BASE}/me/cancel/", {}, format="json").json()["cancel_at_period_end"] is True
    Subscription.objects.filter(pk=sub["id"]).update(current_period_end=timezone.now() + dt.timedelta(days=1))
    assert services.sweep()["reminded"] == 0
    Subscription.objects.filter(pk=sub["id"]).update(current_period_end=timezone.now() - dt.timedelta(minutes=1))
    assert services.sweep()["expired"] == 1
    assert client.get(f"{BASE}/me/").json()["subscription"] is None
    # A new plan can be chosen once the old one ended.
    assert subscribe(client)["status"] == "pending_payment"


def test_abandon_unpaid(auth_client, user):
    client = auth_client(user)
    subscribe(client)
    assert client.delete(f"{BASE}/me/").status_code == 204
    assert client.delete(f"{BASE}/me/").status_code == 404
    assert client.get(f"{BASE}/me/").json()["subscription"] is None


def test_refund_takes_time_back(auth_client, user):
    sub = subscribe(auth_client(user))
    pay(sub["id"])
    adapter = get_payable_adapter("subscriptions.period")
    adapter.on_refunded(sub["id"], reference="unrelated", amount_minor=PRICE, currency="NGN")  # no-op
    assert Subscription.objects.get(pk=sub["id"]).status == "active"
    adapter.on_refunded(sub["id"], reference="ref-1", amount_minor=PRICE, currency="NGN")
    assert Subscription.objects.get(pk=sub["id"]).status == "expired"
    forget(user)
    assert not has_entitlement(user, "premium.ad_free")


def test_public_badge_export_and_purge(auth_client, api_client, user):
    from university.subscriptions.integrations import export_data, purge

    sub = subscribe(auth_client(user))
    assert api_client.get(f"/api/v1/users/by-handle/{user.handle}/").json()["extras"]["premium"] is False
    pay(sub["id"])
    assert api_client.get(f"/api/v1/users/by-handle/{user.handle}/").json()["extras"]["premium"] is True
    exported = export_data(user)["subscriptions"][0]
    assert exported["plan"] == "plus" and exported["periods"][0]["amount_minor"] == PRICE
    purge(user.pk)
    assert not Subscription.objects.exists()
