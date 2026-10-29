from __future__ import annotations

import datetime as dt
import uuid

import pytest
from django.core.files.uploadedfile import SimpleUploadedFile
from django.db import IntegrityError, transaction
from django.utils import timezone

from tests.audience.apps import MEMBERS
from university.core.events import event_bus
from university.core.payables import get_payable_adapter
from university.core.testing import create_user
from university.marketplace import services
from university.marketplace.models import Listing, Order, SellerProfile
from university.permissions.services import assign_role

pytestmark = pytest.mark.django_db
BASE = "/api/v1/marketplace"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\xdac\xc8\xd5\xb8\t\x00\x02t\x01o\xfbJ\xd2\xe1\x00\x00\x00\x00IEND\xaeB`\x82"  # A real 1x1 PNG: decodes with or without Pillow.
INST = "11111111-1111-4111-8111-111111111111"


@pytest.fixture(autouse=True)
def _categories(db):
    services.sync_categories()


@pytest.fixture
def captured():
    seen: list = []
    event_bus.subscribe("payments.*", seen.append)
    event_bus.subscribe("marketplace.*", seen.append)
    yield seen
    event_bus.unsubscribe("payments.*", seen.append)
    event_bus.unsubscribe("marketplace.*", seen.append)


def names(captured, name):
    return [e.payload for e in captured if e.name == name]


def listing(client, **data):
    payload = {
        "title": "HP EliteBook 840",
        "description": "8GB RAM, 256GB SSD",
        "category": "laptops",
        "price_minor": 25000000,
        "quantity": 2,
        "allows_delivery": True,
        "delivery_fee_minor": 150000,
        **data,
    }
    response = client.post(f"{BASE}/listings/", payload, format="json")
    assert response.status_code == 201, response.json()
    created = response.json()
    assert (
        client.post(f"{BASE}/listings/{created['id']}/status/", {"action": "publish"}, format="json").status_code == 200
    )
    return created


def order(client, listing_id, key=None, **data):
    payload = {"listing": listing_id, "quantity": 1, "fulfilment": "pickup", "payment_method": "online", **data}
    return client.post(f"{BASE}/orders/", payload, format="json", HTTP_IDEMPOTENCY_KEY=key or str(uuid.uuid4()))


def pay(order_json):
    get_payable_adapter("marketplace.order").on_paid(
        order_json["id"], reference="PAY-1", amount_minor=order_json["total_minor"], currency=order_json["currency"]
    )


# ----------------------------------------------------------------- listings
def test_listing_lifecycle_and_browse(auth_client, api_client, user, other_user):
    seller = auth_client(user)
    item = listing(seller)
    assert item["status"] == "draft" and item["category"]["key"] == "laptops"
    assert seller.get(f"{BASE}/listings/{item['id']}/").json()["status"] == "active"
    assert SellerProfile.objects.get(user=user).store_name == "ada"
    results = lambda **q: [x["title"] for x in api_client.get(f"{BASE}/listings/", q).json()["results"]]  # noqa: E731
    assert results() == ["HP EliteBook 840"]
    assert results(category="electronics") == ["HP EliteBook 840"]  # Subcategories included.
    assert results(category="books") == []
    assert results(max_price="1000") == [] and results(min_price="1000") == ["HP EliteBook 840"]
    assert results(q="elitebook") == ["HP EliteBook 840"]
    seller.post(f"{BASE}/listings/{item['id']}/status/", {"action": "pause"}, format="json")
    assert results() == [] and api_client.get(f"{BASE}/listings/{item['id']}/").status_code == 404
    assert seller.get(f"{BASE}/listings/{item['id']}/").status_code == 200
    assert (
        auth_client(other_user).patch(f"{BASE}/listings/{item['id']}/", {"title": "x"}, format="json").status_code
        == 404
    )


def test_listing_validation_and_rules(auth_client, user):
    seller = auth_client(user)
    base = {"title": "Thing", "category": "other", "price_minor": 100}
    assert seller.post(f"{BASE}/listings/", {**base, "category": "nope"}, format="json").status_code == 400
    assert seller.post(f"{BASE}/listings/", {**base, "currency": "JPY"}, format="json").status_code == 400
    assert seller.post(f"{BASE}/listings/", {**base, "allows_pickup": False}, format="json").status_code == 400
    assert seller.post(f"{BASE}/listings/", {**base, "visibility": "audience"}, format="json").status_code == 400
    unverified = create_user("new@example.com", handle="newbie", verified=False)
    assert auth_client(unverified).post(f"{BASE}/listings/", base, format="json").status_code == 403


@pytest.mark.security
def test_campus_only_listings(auth_client, api_client, user, other_user):
    seller = auth_client(user)
    payload = {
        "title": "Hostel fridge",
        "category": "kitchen",
        "price_minor": 5000000,
        "visibility": "audience",
        "scope_type": "institution",
        "scope_id": INST,
    }
    assert seller.post(f"{BASE}/listings/", payload, format="json").status_code == 403  # Not a member.
    MEMBERS[str(user.pk)] = [("institution", INST)]
    item = seller.post(f"{BASE}/listings/", payload, format="json").json()
    seller.post(f"{BASE}/listings/{item['id']}/status/", {"action": "publish"}, format="json")
    assert api_client.get(f"{BASE}/listings/{item['id']}/").status_code == 404
    assert auth_client(other_user).get(f"{BASE}/listings/").json()["count"] == 0
    assert order(auth_client(other_user), item["id"]).status_code == 404
    MEMBERS[str(other_user.pk)] = [("institution", INST)]
    assert auth_client(other_user).get(f"{BASE}/listings/").json()["count"] == 1


def test_images(auth_client, user, other_user):
    seller = auth_client(user)
    item = listing(seller)
    ok = seller.post(
        f"{BASE}/listings/{item['id']}/images/", {"file": SimpleUploadedFile("a.png", PNG)}, format="multipart"
    )
    assert ok.status_code == 201 and ok.json()["url"].endswith(".png")
    bad = seller.post(
        f"{BASE}/listings/{item['id']}/images/", {"file": SimpleUploadedFile("a.png", b"<script>")}, format="multipart"
    )
    assert bad.status_code == 400
    assert (
        auth_client(other_user)
        .post(f"{BASE}/listings/{item['id']}/images/", {"file": SimpleUploadedFile("a.png", PNG)}, format="multipart")
        .status_code
        == 403
    )
    assert seller.delete(f"{BASE}/listings/{item['id']}/images/{ok.json()['id']}/").status_code == 204


# ------------------------------------------------------------------- orders
def test_order_reserves_stock_and_needs_idempotency(auth_client, user, other_user, third_user):
    item = listing(auth_client(user), quantity=1)
    buyer = auth_client(other_user)
    no_key = buyer.post(f"{BASE}/orders/", {"listing": item["id"]}, format="json")
    assert no_key.json()["error"]["code"] == "idempotency_key_required"
    first = order(buyer, item["id"], key="buy-1")
    assert first.status_code == 201
    body = first.json()
    assert body["status"] == "pending_payment" and body["total_minor"] == 25000000 and body["expires_at"]
    assert order(buyer, item["id"], key="buy-1").json()["id"] == body["id"]  # Replayed, not duplicated.
    assert Listing.objects.get(pk=item["id"]).status == "sold_out"
    sold = order(auth_client(third_user), item["id"])
    assert sold.status_code == 409 and sold.json()["error"]["code"] == "listing_unavailable"
    assert order(auth_client(user), item["id"]).status_code in (403, 409)  # Own listing.
    # Unpaid orders release their stock.
    Order.objects.update(expires_at=timezone.now() - dt.timedelta(minutes=1))
    assert services.expire_unpaid_orders() == 1
    restocked = Listing.objects.get(pk=item["id"])
    assert restocked.quantity == 1 and restocked.status == "active"


def test_database_guards_stock_and_totals(user, other_user):
    item = (
        Listing.objects.create(seller=user, title="x", category_id=1, price_minor=100, quantity=1, status="active")
        if False
        else None
    )
    category = __import__("university.marketplace.models", fromlist=["MarketCategory"]).MarketCategory.objects.first()
    item = Listing.objects.create(
        seller=user, title="x", category=category, price_minor=100, quantity=1, status="active"
    )
    with pytest.raises(IntegrityError), transaction.atomic():
        Listing.objects.filter(pk=item.pk).update(quantity=-1)
    with pytest.raises(IntegrityError), transaction.atomic():
        Order.objects.create(
            reference="ORD-X",
            buyer=other_user,
            seller=user,
            listing=item,
            title="x",
            unit_price_minor=100,
            quantity=2,
            total_minor=50,
            currency="NGN",
            fulfilment="pickup",
            payment_method="online",
            status="placed",
        )


def test_online_order_happy_path_with_escrow(auth_client, user, other_user, captured):
    seller, buyer = auth_client(user), auth_client(other_user)
    item = listing(seller)
    placed = order(buyer, item["id"], fulfilment="delivery", delivery_details="Room 12, Block B, Zik Hall").json()
    assert placed["total_minor"] == 25150000
    payable = get_payable_adapter("marketplace.order").resolve(placed["id"], other_user)
    assert payable.payee_id == str(user.pk) and payable.escrow is True and payable.amount_minor == 25150000
    with pytest.raises(Exception):
        get_payable_adapter("marketplace.order").resolve(placed["id"], user)  # Only the buyer pays.
    pay(placed)
    assert buyer.get(f"{BASE}/orders/{placed['id']}/").json()["status"] == "paid"
    assert buyer.post(f"{BASE}/orders/{placed['id']}/fulfil/").status_code == 403
    fulfilled = seller.post(f"{BASE}/orders/{placed['id']}/fulfil/").json()
    assert fulfilled["status"] == "fulfilled" and fulfilled["auto_complete_at"]
    done = buyer.post(f"{BASE}/orders/{placed['id']}/confirm/").json()
    assert done["status"] == "completed"
    assert names(captured, "payments.release.requested") == [
        {"purpose": "marketplace.order", "object_id": placed["id"]}
    ]
    assert SellerProfile.objects.get(user=user).sales_count == 1
    review = buyer.post(
        f"{BASE}/orders/{placed['id']}/review/", {"rating": 5, "comment": "Works perfectly"}, format="json"
    )
    assert review.status_code == 201
    assert buyer.post(f"{BASE}/orders/{placed['id']}/review/", {"rating": 1}, format="json").status_code == 409
    seller.post(f"{BASE}/reviews/{review.json()['id']}/reply/", {"reply": "Thank you!"}, format="json")
    profile = auth_client(other_user).get(f"{BASE}/sellers/{user.handle}/").json()
    assert profile["rating"] == 5.0 and profile["rating_count"] == 1


@pytest.mark.security
def test_late_payment_is_rejected_for_automatic_refund(auth_client, user, other_user):
    from university.core.exceptions import Conflict

    item = listing(auth_client(user))
    placed = order(auth_client(other_user), item["id"]).json()
    Order.objects.update(expires_at=timezone.now() - dt.timedelta(minutes=1))
    services.expire_unpaid_orders()
    with pytest.raises(Conflict):
        pay(placed)  # The payments module refunds when this raises.
    with pytest.raises(Conflict):
        get_payable_adapter("marketplace.order").on_paid(placed["id"], reference="P", amount_minor=1, currency="NGN")


def test_auto_complete_releases_escrow(auth_client, user, other_user, captured):
    seller = auth_client(user)
    placed = order(auth_client(other_user), listing(seller)["id"]).json()
    pay(placed)
    seller.post(f"{BASE}/orders/{placed['id']}/fulfil/")
    assert services.auto_complete_orders() == 0
    Order.objects.update(auto_complete_at=timezone.now() - dt.timedelta(minutes=1))
    assert services.auto_complete_orders() == 1
    assert len(names(captured, "payments.release.requested")) == 1


def test_seller_cancels_paid_order_and_buyer_is_refunded(auth_client, user, other_user, captured):
    seller = auth_client(user)
    item = listing(seller, quantity=1)
    placed = order(auth_client(other_user), item["id"]).json()
    pay(placed)
    assert (
        auth_client(other_user).post(f"{BASE}/orders/{placed['id']}/cancel/").status_code == 409
    )  # Paid: buyer can't.
    cancelled = seller.post(f"{BASE}/orders/{placed['id']}/cancel/", {"reason": "Out of stock"}, format="json").json()
    assert cancelled["status"] == "cancelled"
    assert names(captured, "payments.refund.requested")[0]["object_id"] == placed["id"]
    assert Listing.objects.get(pk=item["id"]).quantity == 1


@pytest.mark.security
def test_disputes(auth_client, user, other_user, third_user, captured):
    seller, buyer = auth_client(user), auth_client(other_user)
    placed = order(buyer, listing(seller)["id"]).json()
    pay(placed)
    seller.post(f"{BASE}/orders/{placed['id']}/fulfil/")
    assert buyer.post(f"{BASE}/orders/{placed['id']}/dispute/", {"reason": "short"}, format="json").status_code == 400
    disputed = buyer.post(
        f"{BASE}/orders/{placed['id']}/dispute/", {"reason": "The screen is cracked, not as described."}, format="json"
    ).json()
    assert disputed["status"] == "disputed" and disputed["auto_complete_at"] is None
    Order.objects.update(auto_complete_at=timezone.now() - dt.timedelta(days=1))
    assert services.auto_complete_orders() == 0  # Frozen.
    mediator = auth_client(third_user)
    resolve = f"{BASE}/orders/{placed['id']}/resolve/"
    assert mediator.post(resolve, {"outcome": "refund", "note": "x"}, format="json").status_code == 403
    assign_role(user=third_user, role_key="marketplace_mediator")
    assert mediator.get(f"{BASE}/disputes/").json()["count"] == 1
    # Mediators see the order but not the delivery address.
    assert mediator.get(f"{BASE}/orders/{placed['id']}/").json()["delivery_details"] is None
    partial = mediator.post(
        resolve, {"outcome": "refund", "refund_minor": 5000000, "note": "Partial for damage"}, format="json"
    )
    assert partial.json()["status"] == "completed"
    assert names(captured, "payments.refund.requested")[0]["amount_minor"] == 5000000
    assert names(captured, "payments.release.requested")[0]["object_id"] == placed["id"]


def test_mediators_cannot_decide_their_own_orders(auth_client, user, other_user):
    assign_role(user=user, role_key="marketplace_mediator")
    placed = order(auth_client(other_user), listing(auth_client(user))["id"]).json()
    pay(placed)
    auth_client(other_user).post(
        f"{BASE}/orders/{placed['id']}/dispute/", {"reason": "Never arrived at my hostel."}, format="json"
    )
    blocked = auth_client(user).post(
        f"{BASE}/orders/{placed['id']}/resolve/", {"outcome": "release", "note": "mine"}, format="json"
    )
    assert blocked.status_code == 403 and blocked.json()["error"]["code"] == "conflict_of_interest"


def test_cash_on_pickup(auth_client, user, other_user, captured):
    seller, buyer = auth_client(user), auth_client(other_user)
    item = listing(seller)
    assert (
        order(
            buyer, item["id"], payment_method="cash_on_pickup", fulfilment="delivery", delivery_details="x"
        ).status_code
        == 400
    )
    placed = order(buyer, item["id"], payment_method="cash_on_pickup").json()
    assert placed["status"] == "placed"
    with pytest.raises(Exception):
        get_payable_adapter("marketplace.order").resolve(placed["id"], other_user)  # Nothing to pay online.
    assert buyer.post(f"{BASE}/orders/{placed['id']}/complete/").status_code == 403
    assert seller.post(f"{BASE}/orders/{placed['id']}/complete/").json()["status"] == "completed"
    assert names(captured, "payments.release.requested") == []  # No escrow for cash.
    assert (
        buyer.post(
            f"{BASE}/orders/{placed['id']}/dispute/", {"reason": "It stopped working the next day."}, format="json"
        ).status_code
        == 409
    )


def test_free_items_skip_payment(auth_client, user, other_user):
    item = listing(auth_client(user), price_minor=0, title="Free textbooks", category="textbooks")
    assert order(auth_client(other_user), item["id"]).json()["status"] == "paid"


@pytest.mark.security
def test_orders_are_private(auth_client, user, other_user, third_user):
    placed = order(
        auth_client(other_user),
        listing(auth_client(user))["id"],
        fulfilment="delivery",
        delivery_details="Phone 0803 000 0000",
    ).json()
    assert auth_client(third_user).get(f"{BASE}/orders/{placed['id']}/").status_code == 404
    assert auth_client(user).get(f"{BASE}/orders/{placed['id']}/").json()["delivery_details"].startswith("Phone")
    assert auth_client(user).get(f"{BASE}/me/orders/", {"role": "seller"}).json()["count"] == 1
    assert auth_client(user).get(f"{BASE}/me/orders/").json()["count"] == 0


# --------------------------------------------------------------- moderation
@pytest.mark.security
def test_removing_a_scam_listing_refunds_buyers(auth_client, api_client, user, other_user, third_user, captured):
    from university.core.content import get_moderatable_adapter

    item = listing(auth_client(user), quantity=5)
    paid = order(auth_client(other_user), item["id"]).json()
    pay(paid)
    unpaid = order(auth_client(third_user), item["id"]).json()
    adapter = get_moderatable_adapter("marketplace.listing")
    assert adapter.resolve(item["id"]).author_id == str(user.pk)
    adapter.hide(item["id"], reason="Scam")
    assert api_client.get(f"{BASE}/listings/{item['id']}/").status_code == 404
    assert (
        auth_client(user)
        .post(f"{BASE}/listings/{item['id']}/status/", {"action": "publish"}, format="json")
        .json()["error"]["code"]
        == "listing_hidden"
    )
    adapter.remove(item["id"], reason="Scam")
    statuses = dict(Order.objects.values_list("pk", "status"))
    assert statuses[uuid.UUID(paid["id"])] == "cancelled" and statuses[uuid.UUID(unpaid["id"])] == "cancelled"
    assert [p["object_id"] for p in names(captured, "payments.refund.requested")] == [paid["id"]]


def test_hiding_a_review_recomputes_the_rating(auth_client, user, other_user, third_user):
    from university.core.content import get_moderatable_adapter

    seller = auth_client(user)
    item = listing(seller, quantity=3)
    for buyer_user, rating in ((other_user, 5), (third_user, 1)):
        placed = order(auth_client(buyer_user), item["id"]).json()
        pay(placed)
        auth_client(buyer_user).post(f"{BASE}/orders/{placed['id']}/confirm/")
        auth_client(buyer_user).post(f"{BASE}/orders/{placed['id']}/review/", {"rating": rating}, format="json")
    assert SellerProfile.objects.get(user=user).rating == 3.0
    abusive = seller.get(f"{BASE}/sellers/{user.handle}/reviews/").json()["results"]
    one_star = next(r for r in abusive if r["rating"] == 1)
    get_moderatable_adapter("marketplace.review").hide(one_star["id"], reason="Abusive")
    assert SellerProfile.objects.get(user=user).rating == 5.0


# ----------------------------------------------------------- privacy, misc
def test_export_purge_and_retention(auth_client, user, other_user):
    from university.core.hooks import Hook, hooks
    from university.core.retention import run_retention

    item = listing(auth_client(user))
    placed = order(auth_client(other_user), item["id"], fulfilment="delivery", delivery_details="Zik Hall").json()
    assert (
        hooks.collect(Hook.USER_EXPORT_DATA, other_user)["marketplace_purchases"][0]["delivery_details"] == "Zik Hall"
    )
    seller_export = hooks.collect(Hook.USER_EXPORT_DATA, user)["marketplace_sales"][0]
    assert "delivery_details" not in seller_export  # The buyer's address belongs to the buyer.
    hooks.call(Hook.USER_PURGE, user.pk)
    assert Listing.objects.get(pk=item["id"]).status == "removed"
    assert Order.objects.get(pk=placed["id"]).status == "cancelled"
    another = Order.objects.get(pk=placed["id"])
    Order.objects.filter(pk=another.pk).update(
        delivery_details="Keep?", closed_at=timezone.now() - dt.timedelta(days=60)
    )
    assert run_retention(only=["marketplace.delivery_details"])["marketplace.delivery_details"] == 1
    assert Order.objects.get(pk=placed["id"]).delivery_details == ""


def test_seller_profile_and_badge(auth_client, user):
    from university.core.hooks import Hook, hooks

    me = auth_client(user)
    assert (
        me.patch(f"{BASE}/me/seller/", {"store_name": "Ada's Gadgets"}, format="json").json()["store_name"]
        == "Ada's Gadgets"
    )
    assert hooks.collect(Hook.USER_PUBLIC_PROFILE, user, None)["seller"]["store_name"] == "Ada's Gadgets"


@pytest.mark.security
def test_stock_and_self_purchase_rules(auth_client, user, other_user):
    item = listing(auth_client(user), quantity=2)
    too_many = order(auth_client(other_user), item["id"], quantity=3)
    assert too_many.status_code == 409 and too_many.json()["error"]["code"] == "insufficient_stock"
    own = order(auth_client(user), item["id"])
    assert own.status_code == 403 and own.json()["error"]["code"] == "own_listing"
    assert Listing.objects.get(pk=item["id"]).quantity == 2
