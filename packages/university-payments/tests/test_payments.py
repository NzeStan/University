from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import time

import pytest
from django.utils import timezone

from tests.shop.apps import ITEMS, PAID, REFUNDED
from university.core.events import publish
from university.core.payables import REFUND_REQUESTED, RELEASE_REQUESTED
from university.payments import ledger, services
from university.payments.models import LedgerEntry, PaymentIntent, Refund
from university.payments.providers import testing as gateway
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
BASE = "/api/v1/payments"


def item(payer, amount=500000, **extra):
    key = f"item{len(ITEMS) + 1}"
    ITEMS[key] = {"payer": str(payer.pk), "amount": amount, **extra}
    return key


def checkout(client, object_id, key="k1", **extra):
    return client.post(
        f"{BASE}/checkout/",
        {"purpose": "shop.item", "object_id": object_id, **extra},
        format="json",
        HTTP_IDEMPOTENCY_KEY=key,
    )


def pay(client, object_id, amount=500000, currency="NGN"):
    intent = checkout(client, object_id, key=f"k-{object_id}").json()
    gateway.mark_paid(intent["reference"], amount, currency)
    return client.post(f"{BASE}/{intent['reference']}/verify/").json()


def signed_webhook(client, payload, secret="test-webhook-secret", provider="test"):  # noqa: S107
    body = json.dumps(payload).encode()
    signature = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return client.generic(
        "POST", f"{BASE}/webhooks/{provider}/", body, content_type="application/json", HTTP_X_TEST_SIGNATURE=signature
    )


def assert_balanced():
    for group in LedgerEntry.objects.values_list("group", flat=True).distinct():
        assert sum(LedgerEntry.objects.filter(group=group).values_list("amount_minor", flat=True)) == 0


# ----------------------------------------------------------------- checkout
def test_checkout_requires_idempotency_and_reuses_open_intents(auth_client, user):
    client = auth_client(user)
    key = item(user)
    missing = client.post(f"{BASE}/checkout/", {"purpose": "shop.item", "object_id": key}, format="json")
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "idempotency_key_required"
    first = checkout(client, key).json()
    assert first["status"] == "pending" and first["amount_minor"] == 500000
    assert first["checkout_url"] == f"https://pay.test.invalid/{first['reference']}"
    replay = checkout(client, key)
    assert replay["Idempotent-Replayed"] == "true" and replay.json()["reference"] == first["reference"]
    # A new key for the same item reuses the open checkout instead of double-charging.
    assert checkout(client, key, key="k2").json()["reference"] == first["reference"]
    assert PaymentIntent.objects.count() == 1
    assert gateway.INITIALIZED[0]["metadata"] == {
        "reference": first["reference"],
        "purpose": "shop.item",
        "object_id": key,
    }


@pytest.mark.security
def test_checkout_authorisation_and_validation(auth_client, user, other_user):
    key = item(user)
    assert checkout(auth_client(other_user), key).status_code == 403  # The adapter decides who pays.
    assert (
        auth_client(user)
        .post(f"{BASE}/checkout/", {"purpose": "nope", "object_id": "x"}, format="json", HTTP_IDEMPOTENCY_KEY="z")
        .status_code
        == 404
    )
    evil = checkout(auth_client(user), key, key="k9", callback_url="https://evil.example/steal")
    assert evil.status_code == 400  # Open-redirect protection.
    usd = item(user, currency="JPY")
    assert checkout(auth_client(user), usd, key="k8").json()["error"]["code"] == "currency_unsupported"


# ----------------------------------------------------------- verification
def test_successful_payment_fulfils_once(auth_client, user, captured_events):
    client = auth_client(user)
    key = item(user)
    intent = pay(client, key)
    assert intent["status"] == "succeeded" and intent["paid_at"]
    assert [(key, intent["reference"], 500000)] == PAID
    client.post(f"{BASE}/{intent['reference']}/verify/")  # Repeat redirects are harmless.
    assert len(PAID) == 1
    assert [e.name for e in captured_events].count("payments.payment.succeeded") == 1
    assert ledger.balance("platform:revenue", "NGN") == 500000
    assert_balanced()


def test_unpaid_and_failed_checkouts(auth_client, user):
    from university.payments.providers import ProviderTransaction

    client = auth_client(user)
    intent = checkout(client, item(user)).json()
    assert client.post(f"{BASE}/{intent['reference']}/verify/").json()["status"] == "pending"
    gateway.OUTCOMES[intent["reference"]] = ProviderTransaction(status="failed", amount_minor=0, currency="NGN")
    assert client.post(f"{BASE}/{intent['reference']}/verify/").json()["status"] == "failed"
    assert PAID == []


@pytest.mark.security
def test_wrong_amount_is_refunded_not_fulfilled(auth_client, user):
    client = auth_client(user)
    key = item(user)
    intent = pay(client, key, amount=100)  # Tampered checkout: paid 1 naira.
    assert PAID == []
    payment = PaymentIntent.objects.get(reference=intent["reference"])
    assert payment.failure_reason == "amount_mismatch" and payment.status == "refunded"
    assert Refund.objects.get().amount_minor == 100
    assert_balanced()


@pytest.mark.security
def test_wrong_currency_is_held_for_review(auth_client, user):
    intent = pay(auth_client(user), item(user), currency="USD")
    payment = PaymentIntent.objects.get(reference=intent["reference"])
    assert payment.failure_reason == "currency_mismatch" and PAID == [] and not LedgerEntry.objects.exists()


def test_unfulfillable_payments_are_refunded_automatically(auth_client, user, captured_events):
    key = item(user, too_late=True)
    intent = pay(auth_client(user), key)
    payment = PaymentIntent.objects.get(reference=intent["reference"])
    assert payment.status == "refunded" and payment.failure_reason == "hold_expired"
    assert "payments.payment.unfulfilled" in [e.name for e in captured_events]
    assert [(key, 500000)] == REFUNDED
    assert ledger.balance("provider:test", "NGN") == 0
    assert_balanced()


@pytest.mark.security
def test_transactions_cannot_settle_two_intents(auth_client, user):
    client = auth_client(user)
    a = checkout(client, item(user), key="a").json()
    b = checkout(client, item(user), key="b").json()
    gateway.mark_paid(a["reference"], 500000, "NGN", txn_id="txn_same")
    gateway.mark_paid(b["reference"], 500000, "NGN", txn_id="txn_same")
    client.post(f"{BASE}/{a['reference']}/verify/")
    replayed = client.post(f"{BASE}/{b['reference']}/verify/")
    assert replayed.status_code == 409 and len(PAID) == 1


@pytest.mark.security
def test_payments_are_private(auth_client, user, other_user):
    intent = checkout(auth_client(user), item(user)).json()
    for method, path in (("get", ""), ("post", "verify/"), ("get", "refunds/")):
        assert getattr(auth_client(other_user), method)(f"{BASE}/{intent['reference']}/{path}").status_code == 404
    assert auth_client(other_user).get(f"{BASE}/").json()["count"] == 0


# ----------------------------------------------------------------- webhooks
@pytest.mark.security
def test_webhooks_are_verified_deduplicated_and_reverified(auth_client, api_client, user):
    from university.core.models import WebhookEvent

    client = auth_client(user)
    key = item(user)
    intent = checkout(client, key).json()
    payload = {"id": "evt_1", "type": "charge.success", "reference": intent["reference"], "amount": 999999999}
    assert signed_webhook(api_client, payload, secret="wrong").status_code == 400
    # A genuine notice before the money arrives changes nothing: the provider says "pending".
    assert signed_webhook(api_client, payload).status_code == 200
    assert PaymentIntent.objects.get().status == "pending"
    gateway.mark_paid(intent["reference"], 500000, "NGN")
    payload["id"] = "evt_2"
    assert signed_webhook(api_client, payload).json()["status"] == "processed"
    assert signed_webhook(api_client, payload).json()["status"] == "duplicate"
    assert PaymentIntent.objects.get().status == "succeeded" and len(PAID) == 1
    assert WebhookEvent.objects.get(external_id="evt_2").attempts >= 1
    unknown = {"id": "evt_3", "type": "charge.success", "reference": "PAY-NOT-OURS"}
    assert signed_webhook(api_client, unknown).status_code == 200
    assert api_client.post(f"{BASE}/webhooks/nope/", {}, format="json").status_code == 404


# ---------------------------------------------------------- refunds, escrow
def test_escrow_release_and_seller_balances(auth_client, user, other_user):
    key = item(user, payee=str(other_user.pk), fee=50000, escrow=True)
    pay(auth_client(user), key)
    seller = auth_client(other_user)
    assert seller.get(f"{BASE}/me/balance/").json() == [
        {"currency": "NGN", "held": 450000, "available": 0, "payout": 0}
    ]
    publish(RELEASE_REQUESTED, {"purpose": "shop.item", "object_id": key})
    publish(RELEASE_REQUESTED, {"purpose": "shop.item", "object_id": key})  # Idempotent.
    assert seller.get(f"{BASE}/me/balance/").json() == [
        {"currency": "NGN", "held": 0, "available": 450000, "payout": 0}
    ]
    assert ledger.balance("platform:revenue", "NGN") == 50000
    assert_balanced()


def test_partial_refund_before_release(auth_client, user, other_user, captured_events):
    key = item(user, payee=str(other_user.pk), fee=50000, escrow=True)
    intent = pay(auth_client(user), key)
    publish(REFUND_REQUESTED, {"purpose": "shop.item", "object_id": key, "amount_minor": 100000, "reason": "Damaged"})
    payment = PaymentIntent.objects.get(reference=intent["reference"])
    assert payment.status == "partially_refunded" and payment.amount_refunded_minor == 100000
    # Fees are refunded proportionally: 90k from the seller's escrow, 10k from platform revenue.
    assert ledger.payee_balances(other_user.pk)[0]["held"] == 360000
    assert ledger.balance("platform:revenue", "NGN") == 40000
    assert [(key, 100000)] == REFUNDED
    assert "payments.refund.succeeded" in [e.name for e in captured_events]
    assert_balanced()


def test_staff_refunds_and_pending_refunds(auth_client, user, staff_user):
    intent = pay(auth_client(user), item(user))
    url = f"{BASE}/{intent['reference']}/refunds/"
    assert auth_client(user).post(url, {"reason": "please"}, format="json").status_code == 403
    assign_role(user=staff_user, role_key="finance_officer")
    finance = auth_client(staff_user)
    assert finance.post(url, {"amount_minor": 600000, "reason": "too much"}, format="json").status_code == 400
    gateway.REFUND_MODE["mode"] = "pending"
    refund = finance.post(url, {"amount_minor": 200000, "reason": "Goodwill"}, format="json").json()
    assert refund["status"] == "pending"
    # Pending refunds count against what's refundable.
    assert finance.post(url, {"amount_minor": 400000, "reason": "again"}, format="json").status_code == 400
    # The provider confirms later by webhook.
    from rest_framework.test import APIClient

    signed_webhook(
        APIClient(),
        {
            "id": "evt_r",
            "type": "refund.processed",
            "refund_id": f"rf_{refund['reference']}",
            "refund_status": "succeeded",
        },
    )
    assert Refund.objects.get().status == "succeeded"
    assert PaymentIntent.objects.get().amount_refunded_minor == 200000
    assert_balanced()


def test_refund_retries_then_fails(user, auth_client, captured_events):
    intent = pay(auth_client(user), item(user))
    gateway.REFUND_MODE["mode"] = "error"
    publish(REFUND_REQUESTED, {"purpose": "shop.item", "object_id": next(iter(ITEMS))})
    refund = Refund.objects.get()
    assert refund.status == "pending" and refund.attempts == 1 and refund.error == "test_refund_error"
    for _ in range(4):
        services.retry_refunds()
    refund.refresh_from_db()
    assert refund.status == "failed" and "payments.refund.failed" in [e.name for e in captured_events]
    assert PaymentIntent.objects.get(reference=intent["reference"]).amount_refunded_minor == 0


def test_expire_intents(auth_client, user):
    checkout(auth_client(user), item(user, expires_at=timezone.now() + dt.timedelta(minutes=5)))
    intent = PaymentIntent.objects.get()
    assert intent.expires_at <= timezone.now() + dt.timedelta(minutes=5)  # The payable's hold caps the TTL.
    PaymentIntent.objects.update(expires_at=timezone.now() - dt.timedelta(minutes=1))
    assert services.expire_intents() == 1
    assert PaymentIntent.objects.get().status == "expired"


# ------------------------------------------------------------------ payouts
@pytest.mark.security
def test_payouts(auth_client, user, other_user, staff_user):
    key = item(user, payee=str(other_user.pk), escrow=False)
    pay(auth_client(user), key)
    seller = auth_client(other_user)
    url = f"{BASE}/me/payouts/"
    assert (
        seller.post(
            url, {"amount_minor": 600000, "currency": "NGN", "destination": "GTB ••1234"}, format="json"
        ).json()["error"]["code"]
        == "insufficient_balance"
    )
    assert (
        seller.post(
            url, {"amount_minor": 200000, "currency": "NGN", "destination": "GTB 0123456789"}, format="json"
        ).status_code
        == 400
    )
    payout = seller.post(
        url, {"amount_minor": 300000, "currency": "NGN", "destination": "GTBank ••••6789"}, format="json"
    ).json()
    assert seller.get(f"{BASE}/me/balance/").json()[0] == {
        "currency": "NGN",
        "held": 0,
        "available": 200000,
        "payout": 300000,
    }
    assign_role(user=staff_user, role_key="finance_officer")
    finance = auth_client(staff_user)
    approve = f"{BASE}/payouts/{payout['id']}/approve/"
    assert seller.post(approve, {"external_reference": "x"}, format="json").status_code == 403
    assert finance.post(approve, {}, format="json").status_code == 400
    assert finance.post(approve, {"external_reference": "TRF-001"}, format="json").json()["status"] == "paid"
    assert finance.post(approve, {"external_reference": "TRF-001"}, format="json").status_code == 409
    assert seller.get(f"{BASE}/me/balance/").json()[0]["payout"] == 0
    second = seller.post(
        url, {"amount_minor": 200000, "currency": "NGN", "destination": "Opay ••99"}, format="json"
    ).json()
    seller.post(f"{BASE}/me/payouts/{second['id']}/cancel/")
    assert seller.get(f"{BASE}/me/balance/").json()[0]["available"] == 200000
    assert_balanced()


def test_finance_cannot_pay_themselves(auth_client, user, other_user):
    assign_role(user=other_user, role_key="finance_officer")
    pay(auth_client(user), item(user, payee=str(other_user.pk)))
    payout = services.request_payout(user=other_user, amount_minor=200000, currency="NGN", destination="GTB ••12")
    from university.core.exceptions import PermissionDenied

    with pytest.raises(PermissionDenied):
        services.decide_payout(actor=other_user, payout_id=payout.pk, approve=True, external_reference="x")


# --------------------------------------------------------------- providers
def test_paystack_adapter(monkeypatch):
    from types import SimpleNamespace

    from university.core.webhooks import WebhookVerificationError
    from university.payments.providers import paystack

    calls = []

    def fake(method, url, **kwargs):
        calls.append((method, url, kwargs))
        if url.endswith("/initialize"):
            return {
                "status": True,
                "data": {"authorization_url": "https://checkout.paystack.com/x", "access_code": "ac"},
            }
        if "/verify/" in url:
            return {
                "status": True,
                "data": {
                    "status": "success",
                    "amount": 500000,
                    "currency": "NGN",
                    "id": 42,
                    "paid_at": "2026-05-01T10:00:00Z",
                    "channel": "card",
                },
            }
        return {"status": True, "data": {"status": "pending", "id": 7}}

    monkeypatch.setattr(paystack, "request", fake)
    provider = paystack.PaystackProvider(secret_key="sk_test")
    checkout_ = provider.initialize(
        reference="PAY-1",
        amount_minor=500000,
        currency="NGN",
        email="a@b.c",
        description="Ticket",
        callback_url="https://x/",
        metadata={},
    )
    assert checkout_.checkout_url.endswith("/x") and calls[0][2]["json_body"]["amount"] == 500000
    assert calls[0][2]["headers"]["Authorization"] == "Bearer sk_test"
    txn = provider.verify("PAY-1")
    assert (txn.status, txn.amount_minor, txn.provider_transaction_id) == ("succeeded", 500000, "42")
    assert (
        provider.refund(provider_transaction_id="42", reference="R", amount_minor=100, currency="NGN").status
        == "pending"
    )
    body = json.dumps({"event": "charge.success", "data": {"id": 42, "reference": "PAY-1"}}).encode()
    good = hmac.new(b"sk_test", body, hashlib.sha512).hexdigest()
    notice = provider.parse_webhook(SimpleNamespace(body=body, headers={"X-Paystack-Signature": good}))
    assert notice.reference == "PAY-1" and notice.event_id == "charge.success:42"
    with pytest.raises(WebhookVerificationError):
        provider.parse_webhook(SimpleNamespace(body=body, headers={"X-Paystack-Signature": "bad"}))


def test_flutterwave_adapter(monkeypatch):
    from types import SimpleNamespace

    from university.core.webhooks import WebhookVerificationError
    from university.payments.providers import flutterwave

    def fake(method, url, **kwargs):
        if url.endswith("/payments"):
            assert kwargs["json_body"]["amount"] == "5000.00"  # Major units.
            return {"status": "success", "data": {"link": "https://checkout.flutterwave.com/x"}}
        return {"status": "success", "data": {"status": "successful", "amount": 5000, "currency": "NGN", "id": 9}}

    monkeypatch.setattr(flutterwave, "request", fake)
    provider = flutterwave.FlutterwaveProvider(secret_key="FLWSECK", webhook_hash="h4sh")
    provider.initialize(
        reference="PAY-1",
        amount_minor=500000,
        currency="NGN",
        email="a@b.c",
        description="x",
        callback_url="https://x/",
        metadata={},
    )
    assert provider.verify("PAY-1").amount_minor == 500000
    body = json.dumps({"event": "charge.completed", "data": {"id": 9, "tx_ref": "PAY-1"}}).encode()
    assert provider.parse_webhook(SimpleNamespace(body=body, headers={"verif-hash": "h4sh"})).reference == "PAY-1"
    with pytest.raises(WebhookVerificationError):
        provider.parse_webhook(SimpleNamespace(body=body, headers={"verif-hash": "nope"}))


def test_stripe_adapter(monkeypatch):
    from types import SimpleNamespace

    from university.core.webhooks import WebhookVerificationError
    from university.payments.providers import stripe

    def fake(method, url, **kwargs):
        if url.endswith("/checkout/sessions"):
            assert kwargs["form"]["line_items[0][price_data][unit_amount]"] == "500000"
            return {"id": "cs_1", "url": "https://checkout.stripe.com/x"}
        return {
            "client_reference_id": "PAY-1",
            "payment_status": "paid",
            "amount_total": 500000,
            "currency": "ngn",
            "payment_intent": {"id": "pi_1", "created": 1700000000},
        }

    monkeypatch.setattr(stripe, "request", fake)
    provider = stripe.StripeProvider(secret_key="sk", webhook_secret="whsec")
    assert (
        provider.initialize(
            reference="PAY-1",
            amount_minor=500000,
            currency="NGN",
            email="a@b.c",
            description="x",
            callback_url="https://x/",
            metadata={},
        ).provider_reference
        == "cs_1"
    )
    txn = provider.verify("PAY-1", "cs_1")
    assert (txn.status, txn.currency, txn.provider_transaction_id) == ("succeeded", "NGN", "pi_1")
    body = json.dumps(
        {"id": "evt_1", "type": "checkout.session.completed", "data": {"object": {"client_reference_id": "PAY-1"}}}
    ).encode()
    ts = str(int(time.time()))
    sig = hmac.new(b"whsec", f"{ts}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    notice = provider.parse_webhook(SimpleNamespace(body=body, headers={"Stripe-Signature": f"t={ts},v1=bad,v1={sig}"}))
    assert notice.reference == "PAY-1"
    old = str(int(time.time()) - 3600)
    stale = hmac.new(b"whsec", f"{old}.{body.decode()}".encode(), hashlib.sha256).hexdigest()
    with pytest.raises(WebhookVerificationError):
        provider.parse_webhook(SimpleNamespace(body=body, headers={"Stripe-Signature": f"t={old},v1={stale}"}))


def test_money_helpers():
    from university.payments.money import to_major, to_minor

    assert str(to_major(500050, "NGN")) == "5000.50" and to_minor("5000.50", "NGN") == 500050
    assert str(to_major(1500, "XOF")) == "1500" and to_minor(1500, "XOF") == 1500


def test_export_and_purge(auth_client, user):
    from university.core.hooks import Hook, hooks

    pay(auth_client(user), item(user))
    checkout(auth_client(user), item(user), key="open")
    assert hooks.collect(Hook.USER_EXPORT_DATA, user)["payments"][0]["purpose"] == "shop.item"
    hooks.call(Hook.USER_PURGE, user.pk)
    assert not PaymentIntent.objects.filter(payer=user).exists()
    assert PaymentIntent.objects.filter(status="cancelled", failure_reason="account_deleted").count() == 1
    assert PaymentIntent.objects.filter(status="succeeded").count() == 1  # Financial records are kept.


@pytest.fixture
def captured_events():
    from university.core.events import event_bus

    seen = []
    handler = seen.append
    event_bus.subscribe("payments.*", handler)
    yield seen
    event_bus.unsubscribe("payments.*", handler)


@pytest.mark.security
def test_services_double_check_the_payer(auth_client, user, other_user):
    key = item(user, lenient=True)  # An adapter that forgot to check who pays.
    assert checkout(auth_client(other_user), key).status_code == 403


def test_applying_the_same_transaction_twice_is_harmless(auth_client, user):
    intent = checkout(auth_client(user), item(user)).json()
    gateway.mark_paid(intent["reference"], 500000, "NGN")
    txn = gateway.OUTCOMES[intent["reference"]]
    services.apply_transaction(intent["reference"], txn)
    services.apply_transaction(intent["reference"], txn)
    assert len(PAID) == 1 and LedgerEntry.objects.filter(kind="payment").count() == 2  # One posting, two legs.


def test_funds_are_released_once(auth_client, user, other_user, captured_events):
    key = item(user, payee=str(other_user.pk), escrow=True)
    pay(auth_client(user), key)
    services.release_for("shop.item", key)
    services.release_for("shop.item", key)
    assert [e.name for e in captured_events].count("payments.funds.released") == 1
