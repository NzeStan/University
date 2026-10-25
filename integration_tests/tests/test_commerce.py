"""Payments composed with marketplace, events, creator and notifications (end to end)."""

from __future__ import annotations

import datetime as dt
import hashlib
import hmac
import json
import uuid

import pytest
from django.utils import timezone

from university.core.testing import create_user
from university.creator.services import sync_categories as sync_creator_categories
from university.events.models import Registration
from university.marketplace.services import sync_categories as sync_market_categories
from university.payments.ledger import payee_balances
from university.payments.models import PaymentIntent
from university.payments.providers import reset_providers
from university.payments.providers import testing as gateway
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
PAY = "/api/v1/payments"
MKT = "/api/v1/marketplace"


@pytest.fixture(autouse=True)
def _commerce(settings, db):
    gateway.reset()
    reset_providers()
    sync_market_categories()
    sync_creator_categories()
    settings.UNIVERSITY = {
        "PAYMENTS": {
            "PROVIDERS": {"test": {"class": "university.payments.providers.testing.TestPaymentProvider"}},
            "DEFAULT_PROVIDER": "test",
        },
        "MARKETPLACE": {"PLATFORM_FEE_BPS": 500},  # 5%
        "EVENTS": {"PAID_TICKETS_ENABLED": True},
    }
    yield
    gateway.reset()


def titles(client):
    return [n["title"] for n in client.get("/api/v1/notifications/").json()["results"]]


def checkout(client, purpose, object_id):
    response = client.post(
        f"{PAY}/checkout/",
        {"purpose": purpose, "object_id": str(object_id)},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    assert response.status_code == 201, response.json()
    return response.json()


def provider_confirms(api_client, intent, amount=None, currency="NGN"):
    """The payer completes checkout; the provider sends a signed webhook."""
    gateway.mark_paid(intent["reference"], amount if amount is not None else intent["amount_minor"], currency)
    body = json.dumps(
        {"id": f"evt_{intent['reference']}", "type": "charge.success", "reference": intent["reference"]}
    ).encode()
    signature = hmac.new(b"test-webhook-secret", body, hashlib.sha256).hexdigest()
    response = api_client.generic(
        "POST", f"{PAY}/webhooks/test/", body, content_type="application/json", HTTP_X_TEST_SIGNATURE=signature
    )
    assert response.status_code == 200, response.content


@pytest.fixture
def ngozi(db):
    return create_user("ngozi@example.com", handle="ngozi")


def test_marketplace_order_escrow_to_payout(auth_client, api_client, user, other_user, ngozi):
    seller, buyer = auth_client(user), auth_client(other_user)
    listing = seller.post(
        f"{MKT}/listings/",
        {"title": "Casio fx-991ES", "category": "accessories", "price_minor": 1500000, "quantity": 3},
        format="json",
    ).json()
    seller.post(f"{MKT}/listings/{listing['id']}/status/", {"action": "publish"}, format="json")
    order = buyer.post(
        f"{MKT}/orders/", {"listing": listing["id"]}, format="json", HTTP_IDEMPOTENCY_KEY="order-1"
    ).json()
    assert titles(seller) == ["New order for Casio fx-991ES."]
    intent = checkout(buyer, "marketplace.order", order["id"])
    assert intent["amount_minor"] == 1500000
    provider_confirms(api_client, intent)
    assert buyer.get(f"{MKT}/orders/{order['id']}/").json()["status"] == "paid"
    assert titles(seller)[0] == "An order for Casio fx-991ES was paid. Time to fulfil it."
    # The seller's share (minus the 5% fee) is held in escrow until the buyer confirms.
    assert payee_balances(user.pk) == [{"currency": "NGN", "held": 1425000, "available": 0, "payout": 0}]
    seller.post(f"{MKT}/orders/{order['id']}/fulfil/")
    buyer.post(f"{MKT}/orders/{order['id']}/confirm/")
    assert payee_balances(user.pk) == [{"currency": "NGN", "held": 0, "available": 1425000, "payout": 0}]
    # The seller withdraws; finance pays it out.
    payout = seller.post(
        f"{PAY}/me/payouts/",
        {"amount_minor": 1425000, "currency": "NGN", "destination": "GTBank ••••6789"},
        format="json",
    ).json()
    assign_role(user=ngozi, role_key="finance_officer")
    auth_client(ngozi).post(f"{PAY}/payouts/{payout['id']}/approve/", {"external_reference": "TRF-9"}, format="json")
    assert titles(seller)[0] == "Your payout was sent."
    assert payee_balances(user.pk)[0]["available"] == 0


def test_seller_cancellation_refunds_the_buyer(auth_client, api_client, user, other_user):
    seller, buyer = auth_client(user), auth_client(other_user)
    listing = seller.post(
        f"{MKT}/listings/", {"title": "Textbook", "category": "textbooks", "price_minor": 800000}, format="json"
    ).json()
    seller.post(f"{MKT}/listings/{listing['id']}/status/", {"action": "publish"}, format="json")
    order = buyer.post(f"{MKT}/orders/", {"listing": listing["id"]}, format="json", HTTP_IDEMPOTENCY_KEY="o").json()
    provider_confirms(api_client, checkout(buyer, "marketplace.order", order["id"]))
    seller.post(f"{MKT}/orders/{order['id']}/cancel/", {"reason": "Sold elsewhere"}, format="json")
    payment = PaymentIntent.objects.get()
    assert payment.status == "refunded" and payment.amount_refunded_minor == 800000
    assert {"A refund was issued to you.", "An order for Textbook was cancelled."} <= set(titles(buyer))
    assert payee_balances(user.pk)[0]["held"] == 0


def test_paid_event_tickets(auth_client, api_client, user, other_user, ngozi):
    host = auth_client(user)
    event = host.post(
        "/api/v1/events/",
        {
            "title": "Tech Summit",
            "location_details": "Hall A",
            "capacity": 1,
            "starts_at": (timezone.now() + dt.timedelta(days=3)).isoformat(),
            "ends_at": (timezone.now() + dt.timedelta(days=3, hours=4)).isoformat(),
        },
        format="json",
    ).json()
    host.post(f"/api/v1/events/{event['id']}/publish/")
    vip = host.post(
        f"/api/v1/events/{event['id']}/ticket-types/", {"name": "VIP", "price_minor": 500000}, format="json"
    ).json()
    held = (
        auth_client(other_user)
        .post(f"/api/v1/events/{event['id']}/register/", {"ticket_type": vip["id"]}, format="json")
        .json()
    )
    assert held["status"] == "pending_payment"
    # Someone else can't pay for (or hijack) this ticket.
    stranger = auth_client(ngozi).post(
        f"{PAY}/checkout/",
        {"purpose": "events.registration", "object_id": held["id"]},
        format="json",
        HTTP_IDEMPOTENCY_KEY="x",
    )
    assert stranger.status_code == 404
    provider_confirms(api_client, checkout(auth_client(other_user), "events.registration", held["id"]))
    ticket = auth_client(other_user).get(f"/api/v1/events/{event['id']}/registration/").json()
    assert ticket["status"] == "confirmed" and ticket["ticket_code"]
    assert "You're registered for Tech Summit." in titles(auth_client(other_user))
    # The organizer cancels the event: paid tickets are refunded.
    host.post(f"/api/v1/events/{event['id']}/cancel/", {"reason": "Venue issue"}, format="json")
    assert PaymentIntent.objects.get().status == "refunded"


def test_late_ticket_payment_is_refunded_automatically(auth_client, api_client, user, other_user):
    host = auth_client(user)
    event = host.post(
        "/api/v1/events/",
        {
            "title": "Gala",
            "location_details": "Hall B",
            "starts_at": (timezone.now() + dt.timedelta(days=3)).isoformat(),
            "ends_at": (timezone.now() + dt.timedelta(days=3, hours=4)).isoformat(),
        },
        format="json",
    ).json()
    host.post(f"/api/v1/events/{event['id']}/publish/")
    ticket = host.post(
        f"/api/v1/events/{event['id']}/ticket-types/", {"name": "Regular", "price_minor": 200000}, format="json"
    ).json()
    held = (
        auth_client(other_user)
        .post(f"/api/v1/events/{event['id']}/register/", {"ticket_type": ticket["id"]}, format="json")
        .json()
    )
    intent = checkout(auth_client(other_user), "events.registration", held["id"])
    # The hold expires before the money arrives.
    from university.events.services import release_expired_holds

    Registration.objects.filter(pk=held["id"]).update(hold_expires_at=timezone.now() - dt.timedelta(minutes=1))
    release_expired_holds()
    provider_confirms(api_client, intent)
    payment = PaymentIntent.objects.get()
    assert payment.status == "refunded" and payment.failure_reason == "payment_too_late"
    assert "Your payment couldn't be applied, so it's being refunded." in titles(auth_client(other_user))


def test_sponsorship_fee_escrow(auth_client, api_client, user, other_user):
    brand, creator = auth_client(user), auth_client(other_user)
    creator.post("/api/v1/me/creator/", {"headline": "Campus creator", "categories": ["comedy"]}, format="json")
    campaign = brand.post(
        "/api/v1/campaigns/", {"brand_name": "Bank", "title": "Freshers", "brief": "Promote."}, format="json"
    ).json()
    brand.post(f"/api/v1/campaigns/{campaign['id']}/publish/")
    participation = creator.post(
        f"/api/v1/campaigns/{campaign['id']}/apply/",
        {"pitch": "Pick me please, I'm great.", "proposed_fee_minor": 3000000},
        format="json",
    ).json()
    brand.post(f"/api/v1/participations/{participation['id']}/decision/", {"action": "accept"}, format="json")
    provider_confirms(api_client, checkout(brand, "creator.participation", participation["id"]))
    assert payee_balances(other_user.pk)[0]["held"] == 3000000
    assert checkout_fails_when_paid(brand, participation["id"])
    brand.post(f"/api/v1/participations/{participation['id']}/decision/", {"action": "complete"}, format="json")
    assert payee_balances(other_user.pk)[0]["available"] == 3000000


def checkout_fails_when_paid(client, participation_id):
    response = client.post(
        f"{PAY}/checkout/",
        {"purpose": "creator.participation", "object_id": participation_id},
        format="json",
        HTTP_IDEMPOTENCY_KEY=str(uuid.uuid4()),
    )
    return response.status_code == 409 and response.json()["error"]["code"] == "already_paid"


def test_all_payable_purposes_registered():
    from university.core.payables import payable_purposes

    assert payable_purposes() == ["creator.participation", "events.registration", "marketplace.order"]
