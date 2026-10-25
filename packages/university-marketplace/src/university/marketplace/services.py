"""Marketplace services: listings, sellers, orders, disputes and reviews.

Order lifecycle::

    online:  pending_payment ─► paid ─► fulfilled ─► completed (buyer confirms, or automatically)
                    │             │          └──► disputed ─► completed / refunded (mediator)
                    └► cancelled  └► cancelled + refund (seller)
    cash:    placed ─► completed (seller confirms the handover)   └► cancelled

Escrow is handled by the payments module through Core's contract: on
completion this module publishes ``payments.release.requested``; refunds are
``payments.refund.requested``. Stock is reserved when an order is placed and
returned if it's cancelled or expires unpaid.
"""

from __future__ import annotations

import datetime as dt
import secrets
from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from university.audit.services import record as audit
from university.core.content import ensure_can_create
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.payables import REFUND_REQUESTED, RELEASE_REQUESTED
from university.core.providers import get_spam_filter
from university.core.providers.spam import SpamAction
from university.core.ratelimit import rate_limit
from university.core.tasks import task
from university.core.uploads import FileUploadValidator
from university.marketplace import events
from university.marketplace.conf import marketplace_settings
from university.marketplace.constants import (
    LISTING_CONTENT_TYPE,
    ORDER_PURPOSE,
    Fulfilment,
    ListingStatus,
    ListingVisibility,
    OrderStatus,
    PaymentMethod,
)
from university.marketplace.models import Listing, ListingImage, MarketCategory, Order, Review, SellerProfile
from university.marketplace.selectors import can_mediate, get_listing, get_order_for, get_visible_listing
from university.permissions.services import authorize

S = OrderStatus


def _screen(text: str, actor: Any) -> None:
    if not text.strip():
        return
    verdict = get_spam_filter().check(text, actor=actor, context={"kind": "marketplace"})
    if verdict.action == SpamAction.REJECT:
        raise ValidationError(
            "This content was rejected by our spam filter.",
            code="content_rejected",
            details={"reasons": list(verdict.reasons)},
        )


# --------------------------------------------------------------- categories
def sync_categories() -> None:
    def walk(tree: Mapping[str, Any], parent: MarketCategory | None) -> None:
        for position, (key, value) in enumerate(tree.items()):
            name = value if isinstance(value, str) else value.get("name", key)
            category, _ = MarketCategory.objects.get_or_create(
                key=key, defaults={"name": name, "parent": parent, "position": position}
            )
            if isinstance(value, Mapping) and value.get("children"):
                walk(value["children"], category)

    walk(marketplace_settings.get("CATEGORIES") or {}, None)


# ------------------------------------------------------------------ sellers
def seller_profile(user: Any) -> SellerProfile:
    profile = SellerProfile.objects.filter(user=user).first()
    if profile is None:
        profile, _ = SellerProfile.objects.get_or_create(
            user=user, defaults={"store_name": (user.display_name or user.handle or "Seller")[:80]}
        )
    return profile


@transaction.atomic
def update_seller_profile(*, user: Any, data: Mapping[str, Any]) -> SellerProfile:
    profile = seller_profile(user)
    if "store_name" in data:
        profile.store_name = str(data["store_name"]).strip()[:80] or profile.store_name
    if "about" in data:
        profile.about = str(data["about"])[:2000]
    _screen(f"{profile.store_name}\n{profile.about}", user)
    profile.save()
    return profile


# ----------------------------------------------------------------- listings
LISTING_FIELDS = (
    "title",
    "description",
    "condition",
    "price_minor",
    "currency",
    "quantity",
    "visibility",
    "city",
    "location_note",
    "allows_pickup",
    "allows_delivery",
    "delivery_fee_minor",
    "allows_cash_on_pickup",
)


def _validate_listing(listing: Listing) -> None:
    if listing.currency not in marketplace_settings.get("CURRENCIES", []):
        raise ValidationError(details={"currency": ["Unsupported currency."]})
    if not (listing.allows_pickup or listing.allows_delivery):
        raise ValidationError(details={"allows_pickup": ["Offer pickup, delivery or both."]})
    if listing.visibility == ListingVisibility.AUDIENCE and not listing.scope_type:
        raise ValidationError(details={"visibility": ["Members-only listings need a scope."]})
    if not listing.title.strip():
        raise ValidationError(details={"title": ["Required."]})


def _category(key: Any) -> MarketCategory:
    category = MarketCategory.objects.filter(key=key, is_active=True).first()
    if category is None:
        raise ValidationError(details={"category": ["Unknown category."]})
    return category


@transaction.atomic
def create_listing(
    *, seller: Any, data: Mapping[str, Any], category: str, scope_type: str = "", scope_id: Any = ""
) -> Listing:
    rate_limit("marketplace_listing_create", key=str(seller.pk))
    ensure_can_create(seller, LISTING_CONTENT_TYPE)
    if marketplace_settings.get("REQUIRE_VERIFIED_EMAIL", True) and not seller.email_verified_at:
        raise PermissionDenied("Verify your email address to sell.", code="email_not_verified")
    scope_id = str(scope_id or "")
    if scope_type or scope_id:
        from university.core.audiences import is_member

        if not (scope_type and scope_id) or not is_member(seller, scope_type, scope_id):
            raise PermissionDenied("You can only sell in marketplaces you belong to.", code="not_a_member")
    active = Listing.objects.filter(seller=seller, status__in=[ListingStatus.ACTIVE, ListingStatus.DRAFT]).count()
    if active >= int(marketplace_settings.get("MAX_ACTIVE_LISTINGS", 50)):
        raise PermissionDenied("You've reached the listing limit.", code="listing_limit_reached")
    fields = {k: v for k, v in data.items() if k in LISTING_FIELDS}
    fields.setdefault("currency", marketplace_settings.get("DEFAULT_CURRENCY", "NGN"))
    listing = Listing(seller=seller, category=_category(category), scope_type=scope_type, scope_id=scope_id, **fields)
    _validate_listing(listing)
    _screen(f"{listing.title}\n{listing.description}", seller)
    listing.save()
    seller_profile(seller)
    return listing


def _own_listing(user: Any, listing_id: Any) -> Listing:
    listing = Listing.objects.select_for_update().filter(pk=get_listing(listing_id).pk).first()
    if listing.seller_id != user.pk:
        raise PermissionDenied("This isn't your listing.")
    return listing


@transaction.atomic
def update_listing(*, user: Any, listing_id: Any, data: Mapping[str, Any], category: str | None = None) -> Listing:
    listing = _own_listing(user, listing_id)
    if listing.status == ListingStatus.REMOVED:
        raise Conflict("This listing was removed.", code="listing_removed")
    for key, value in data.items():
        if key in LISTING_FIELDS:
            setattr(listing, key, value)
    if category:
        listing.category = _category(category)
    _validate_listing(listing)
    _screen(f"{listing.title}\n{listing.description}", user)
    if listing.status == ListingStatus.SOLD_OUT and listing.quantity > 0:
        listing.status = ListingStatus.ACTIVE
    elif listing.status == ListingStatus.ACTIVE and listing.quantity == 0:
        listing.status = ListingStatus.SOLD_OUT
    listing.save()
    return listing


@transaction.atomic
def set_listing_status(*, user: Any, listing_id: Any, action: str) -> Listing:
    listing = _own_listing(user, listing_id)
    if listing.status == ListingStatus.REMOVED:
        raise Conflict("This listing was removed.", code="listing_removed")
    if action == "publish":
        if listing.hidden_at:
            raise PermissionDenied("This listing was hidden by the moderators.", code="listing_hidden")
        listing.status = ListingStatus.ACTIVE if listing.quantity > 0 else ListingStatus.SOLD_OUT
        if not listing.published_at:
            listing.published_at = timezone.now()
            publish(events.LISTING_PUBLISHED, {"listing_id": listing.pk, "seller_id": user.pk}, actor=user)
    elif action == "pause":
        listing.status = ListingStatus.PAUSED
    elif action == "remove":
        listing.status = ListingStatus.REMOVED
    else:
        raise ValidationError(details={"action": ["Unknown action."]})
    listing.save(update_fields=["status", "published_at", "updated_at"])
    return listing


@transaction.atomic
def add_image(*, user: Any, listing_id: Any, file: Any, alt_text: str = "") -> ListingImage:
    listing = _own_listing(user, listing_id)
    if listing.images.count() >= int(marketplace_settings.get("MAX_IMAGES", 8)):
        raise ValidationError("This listing has the maximum number of images.", code="image_limit")
    validator = FileUploadValidator(
        allowed_mime_types=marketplace_settings.get("IMAGE_MIME_TYPES"),
        max_bytes=marketplace_settings.get("IMAGE_MAX_BYTES"),
    )
    try:
        validator(file)
    except DjangoValidationError as exc:
        raise ValidationError(details={"file": exc.messages}) from None
    image = ListingImage(listing=listing, alt_text=alt_text[:200], position=listing.images.count())
    image._upload_file = file
    image.file.save(file.name, file, save=False)
    image.save()
    return image


@transaction.atomic
def remove_image(*, user: Any, listing_id: Any, image_id: Any) -> None:
    listing = _own_listing(user, listing_id)
    image = listing.images.filter(pk=image_id).first()
    if image is None:
        raise NotFound("Image not found.")
    name = image.file.name
    storage = image.file.storage
    image.delete()
    transaction.on_commit(lambda: storage.delete(name))


# ------------------------------------------------------------------- orders
def _payload(order: Order, **extra: Any) -> dict[str, Any]:
    return {
        "order_id": order.pk,
        "reference": order.reference,
        "buyer_id": order.buyer_id,
        "seller_id": order.seller_id,
        "listing_id": order.listing_id,
        "status": order.status,
        **extra,
    }


def _restock(order: Order) -> None:
    if order.restocked or order.listing_id is None:
        return
    listing = Listing.objects.select_for_update().get(pk=order.listing_id)
    listing.quantity = F("quantity") + order.quantity
    if listing.status == ListingStatus.SOLD_OUT:
        listing.status = ListingStatus.ACTIVE
    listing.save(update_fields=["quantity", "status", "updated_at"])
    order.restocked = True


@transaction.atomic
def place_order(
    *,
    buyer: Any,
    listing_id: Any,
    quantity: int,
    fulfilment: str,
    payment_method: str,
    delivery_details: str = "",
) -> Order:
    rate_limit("marketplace_order", key=str(buyer.pk))
    visible = get_visible_listing(buyer, listing_id)
    listing = Listing.objects.select_for_update().get(pk=visible.pk)
    if listing.seller_id == buyer.pk:
        raise PermissionDenied("You can't buy your own listing.", code="own_listing")
    if listing.status != ListingStatus.ACTIVE or listing.hidden_at:
        raise Conflict("This listing isn't available.", code="listing_unavailable")
    max_qty = int(marketplace_settings.get("MAX_QUANTITY_PER_ORDER", 20))
    if not 1 <= quantity <= max_qty:
        raise ValidationError(details={"quantity": [f"Choose 1 to {max_qty}."]})
    if quantity > listing.quantity:
        raise Conflict("Not enough in stock.", code="insufficient_stock", details={"available": listing.quantity})
    if fulfilment == Fulfilment.PICKUP and not listing.allows_pickup:
        raise ValidationError(details={"fulfilment": ["This seller doesn't offer pickup."]})
    if fulfilment == Fulfilment.DELIVERY and not listing.allows_delivery:
        raise ValidationError(details={"fulfilment": ["This seller doesn't deliver."]})
    if payment_method == PaymentMethod.CASH_ON_PICKUP:
        if not (marketplace_settings.get("ALLOW_CASH_ON_PICKUP", True) and listing.allows_cash_on_pickup):
            raise ValidationError(details={"payment_method": ["Cash on pickup isn't available."]})
        if fulfilment != Fulfilment.PICKUP:
            raise ValidationError(details={"payment_method": ["Cash is only for pickup orders."]})
    delivery_details = (delivery_details or "").strip()[:1000]
    if fulfilment == Fulfilment.DELIVERY and not delivery_details:
        raise ValidationError(details={"delivery_details": ["Where should it be delivered?"]})
    delivery_fee = listing.delivery_fee_minor if fulfilment == Fulfilment.DELIVERY else 0
    total = listing.price_minor * quantity + delivery_fee
    online = payment_method == PaymentMethod.ONLINE
    now = timezone.now()
    if not online:
        status = S.PLACED
    elif total == 0:
        status = S.PAID  # Free items need no payment.
    else:
        status = S.PENDING_PAYMENT
    order = Order.objects.create(
        reference=f"ORD-{secrets.token_hex(6).upper()}",
        buyer=buyer,
        seller_id=listing.seller_id,
        listing=listing,
        title=listing.title,
        unit_price_minor=listing.price_minor,
        quantity=quantity,
        delivery_fee_minor=delivery_fee,
        total_minor=total,
        currency=listing.currency,
        platform_fee_minor=total * int(marketplace_settings.get("PLATFORM_FEE_BPS", 0)) // 10000 if online else 0,
        fulfilment=fulfilment,
        payment_method=payment_method,
        delivery_details=delivery_details,
        status=status,
        expires_at=now + dt.timedelta(minutes=int(marketplace_settings.get("PAYMENT_WINDOW_MINUTES", 30)))
        if status == S.PENDING_PAYMENT
        else None,
        paid_at=now if status == S.PAID else None,
    )
    listing.quantity -= quantity
    if listing.quantity == 0:
        listing.status = ListingStatus.SOLD_OUT
    listing.save(update_fields=["quantity", "status", "updated_at"])
    publish(events.ORDER_CREATED, _payload(order), actor=buyer)
    if status == S.PAID:
        publish(events.ORDER_PAID, _payload(order), actor=buyer)
    return order


def _locked_order(order_id: Any) -> Order:
    return Order.objects.select_for_update().get(pk=order_id)


def _close(order: Order, status: str, **fields: Any) -> None:
    order.status = status
    order.closed_at = timezone.now()
    for key, value in fields.items():
        setattr(order, key, value)
    order.save()


@transaction.atomic
def cancel_order(*, user: Any, order_id: Any, reason: str = "") -> Order:
    order = _locked_order(get_order_for(user, order_id).pk)
    is_buyer, is_seller = user.pk == order.buyer_id, user.pk == order.seller_id
    refund = False
    if is_buyer and order.status in (S.PENDING_PAYMENT, S.PLACED):
        pass
    elif is_seller and order.status in (S.PENDING_PAYMENT, S.PLACED, S.PAID):
        refund = order.status == S.PAID and order.payment_method == PaymentMethod.ONLINE and order.total_minor > 0
    else:
        raise Conflict("This order can't be cancelled now.", code="not_cancellable")
    _restock(order)
    _close(
        order,
        S.CANCELLED,
        cancelled_at=timezone.now(),
        cancel_reason=reason[:255] or ("buyer" if is_buyer else "seller"),
    )
    if refund:
        publish(
            REFUND_REQUESTED, {"purpose": ORDER_PURPOSE, "object_id": order.pk, "reason": "Cancelled by the seller"}
        )
    publish(events.ORDER_CANCELLED, _payload(order, cancelled_by="buyer" if is_buyer else "seller"), actor=user)
    return order


def mark_paid(order_id: Any, *, reference: str, amount_minor: int, currency: str) -> Order:
    """Called through the ``marketplace.order`` payable once a payment is verified."""
    order = _locked_order(order_id)
    if order.status != S.PENDING_PAYMENT:
        raise Conflict("This order is no longer awaiting payment.", code="order_not_payable")
    if amount_minor != order.total_minor or currency != order.currency:
        raise Conflict("The payment doesn't match the order.", code="payment_mismatch")
    order.status = S.PAID
    order.paid_at = timezone.now()
    order.payment_reference = reference[:64]
    order.expires_at = None
    order.save(update_fields=["status", "paid_at", "payment_reference", "expires_at", "updated_at"])
    publish(events.ORDER_PAID, _payload(order))
    return order


@transaction.atomic
def fulfil_order(*, user: Any, order_id: Any) -> Order:
    order = _locked_order(get_order_for(user, order_id).pk)
    if user.pk != order.seller_id:
        raise PermissionDenied("Only the seller fulfils orders.")
    if order.status != S.PAID:
        raise Conflict("Only paid orders can be fulfilled.", code="not_paid")
    now = timezone.now()
    order.status = S.FULFILLED
    order.fulfilled_at = now
    order.auto_complete_at = now + dt.timedelta(days=int(marketplace_settings.get("AUTO_COMPLETE_DAYS", 7)))
    order.save(update_fields=["status", "fulfilled_at", "auto_complete_at", "updated_at"])
    publish(events.ORDER_FULFILLED, _payload(order), actor=user)
    return order


def _complete(order: Order, actor: Any = None) -> None:
    _close(order, S.COMPLETED, completed_at=timezone.now())
    SellerProfile.objects.filter(user_id=order.seller_id).update(sales_count=F("sales_count") + 1)
    if order.payment_method == PaymentMethod.ONLINE and order.total_minor > 0:
        publish(RELEASE_REQUESTED, {"purpose": ORDER_PURPOSE, "object_id": order.pk})
    publish(events.ORDER_COMPLETED, _payload(order), actor=actor)


@transaction.atomic
def confirm_received(*, user: Any, order_id: Any) -> Order:
    """The buyer confirms delivery: escrow is released to the seller."""
    order = _locked_order(get_order_for(user, order_id).pk)
    if user.pk != order.buyer_id:
        raise PermissionDenied("Only the buyer confirms delivery.")
    if order.status not in (S.FULFILLED, S.PAID):
        raise Conflict("This order can't be confirmed now.", code="not_confirmable")
    _complete(order, user)
    return order


@transaction.atomic
def complete_cash_order(*, user: Any, order_id: Any) -> Order:
    """The seller confirms the handover and cash payment."""
    order = _locked_order(get_order_for(user, order_id).pk)
    if user.pk != order.seller_id:
        raise PermissionDenied("Only the seller completes cash orders.")
    if order.status != S.PLACED:
        raise Conflict("Only placed cash orders can be completed.", code="not_cash_order")
    _complete(order, user)
    return order


@transaction.atomic
def open_dispute(*, user: Any, order_id: Any, reason: str) -> Order:
    order = _locked_order(get_order_for(user, order_id).pk)
    if user.pk != order.buyer_id:
        raise PermissionDenied("Only the buyer opens disputes.")
    if order.payment_method != PaymentMethod.ONLINE or order.status not in (S.PAID, S.FULFILLED):
        raise Conflict("Disputes are for paid online orders that aren't completed.", code="not_disputable")
    reason = (reason or "").strip()
    if not 10 <= len(reason) <= 2000:
        raise ValidationError(details={"reason": ["Explain the problem in 10 to 2000 characters."]})
    order.status = S.DISPUTED
    order.disputed_at = timezone.now()
    order.dispute_reason = reason
    order.auto_complete_at = None  # Frozen until a mediator decides.
    order.save(update_fields=["status", "disputed_at", "dispute_reason", "auto_complete_at", "updated_at"])
    audit("marketplace.order.disputed", actor=user, target=order, category="marketplace")
    publish(events.ORDER_DISPUTED, _payload(order), actor=user)
    return order


@transaction.atomic
def resolve_dispute(*, actor: Any, order_id: Any, outcome: str, refund_minor: int | None = None, note: str) -> Order:
    """A mediator refunds the buyer (fully or partly) or releases the money to the seller."""
    authorize(actor, "marketplace.disputes.resolve", audit_denial=True)
    order = _locked_order(get_order_for(actor, order_id).pk)
    if actor.pk in (order.buyer_id, order.seller_id):
        raise PermissionDenied("You can't mediate your own order.", code="conflict_of_interest")
    if order.status != S.DISPUTED:
        raise Conflict("This order isn't disputed.", code="not_disputed")
    if not (note or "").strip():
        raise ValidationError(details={"note": ["Explain the decision."]})
    order.resolution = note[:500]
    order.resolved_by = actor
    if outcome == "release":
        _complete(order, actor)
    elif outcome == "refund":
        amount = refund_minor or order.total_minor
        if not 0 < amount <= order.total_minor:
            raise ValidationError(details={"refund_minor": ["Between 1 and the order total."]})
        publish(
            REFUND_REQUESTED,
            {"purpose": ORDER_PURPOSE, "object_id": order.pk, "amount_minor": amount, "reason": "Dispute resolved"},
        )
        if amount < order.total_minor:
            _complete(order, actor)  # The rest goes to the seller.
        else:
            _close(order, S.REFUNDED)
    else:
        raise ValidationError(details={"outcome": ["Choose refund or release."]})
    audit(
        "marketplace.dispute.resolved",
        actor=actor,
        target=order,
        category="marketplace",
        metadata={"outcome": outcome, "refund_minor": refund_minor},
    )
    publish(events.DISPUTE_RESOLVED, _payload(order, outcome=outcome), actor=actor)
    return order


def mark_refunded(order_id: Any, amount_minor: int) -> None:
    """A full refund by finance closes an open order (called through the payable)."""
    order = _locked_order(order_id)
    if amount_minor >= order.total_minor and order.status in (S.PAID, S.FULFILLED, S.DISPUTED):
        _close(order, S.REFUNDED)
        publish(events.ORDER_REFUNDED, _payload(order))
    elif order.status in (S.CANCELLED, S.REFUNDED, S.COMPLETED):
        publish(events.ORDER_REFUNDED, _payload(order, partial=amount_minor < order.total_minor))


@task(name="university.marketplace.expire_unpaid_orders")
def expire_unpaid_orders() -> int:
    expired = 0
    for order_id in list(
        Order.objects.filter(status=S.PENDING_PAYMENT, expires_at__lt=timezone.now()).values_list("pk", flat=True)
    ):
        with transaction.atomic():
            order = _locked_order(order_id)
            if order.status != S.PENDING_PAYMENT:
                continue
            _restock(order)
            _close(order, S.CANCELLED, cancelled_at=timezone.now(), cancel_reason="payment_expired")
            publish(events.ORDER_CANCELLED, _payload(order, cancelled_by="system"))
            expired += 1
    return expired


@task(name="university.marketplace.auto_complete_orders")
def auto_complete_orders() -> int:
    done = 0
    for order_id in list(
        Order.objects.filter(status=S.FULFILLED, auto_complete_at__lt=timezone.now()).values_list("pk", flat=True)
    ):
        with transaction.atomic():
            order = _locked_order(order_id)
            if order.status == S.FULFILLED:
                _complete(order)
                done += 1
    return done


# ------------------------------------------------------------------ reviews
def _recompute_rating(seller_id: Any) -> None:
    from django.db.models import Count, Sum

    agg = Review.objects.filter(seller_id=seller_id, hidden_at__isnull=True).aggregate(s=Sum("rating"), c=Count("id"))
    SellerProfile.objects.filter(user_id=seller_id).update(rating_sum=agg["s"] or 0, rating_count=agg["c"] or 0)


@transaction.atomic
def create_review(*, user: Any, order_id: Any, rating: int, comment: str = "") -> Review:
    order = _locked_order(get_order_for(user, order_id).pk)
    if user.pk != order.buyer_id:
        raise PermissionDenied("Only the buyer reviews an order.")
    if order.status != S.COMPLETED:
        raise Conflict("Review completed orders only.", code="not_completed")
    if Review.objects.filter(order=order).exists():
        raise Conflict("You already reviewed this order.", code="already_reviewed")
    if not 1 <= int(rating) <= 5:
        raise ValidationError(details={"rating": ["1 to 5."]})
    comment = (comment or "").strip()[:2000]
    _screen(comment, user)
    review = Review.objects.create(
        order=order,
        reviewer=user,
        seller_id=order.seller_id,
        listing_id=order.listing_id,
        rating=int(rating),
        comment=comment,
    )
    _recompute_rating(order.seller_id)
    publish(
        events.REVIEW_CREATED, {"review_id": review.pk, "order_id": order.pk, "seller_id": order.seller_id}, actor=user
    )
    return review


@transaction.atomic
def reply_to_review(*, user: Any, review_id: Any, reply: str) -> Review:
    review = Review.objects.select_for_update().filter(pk=review_id, seller=user).first()
    if review is None:
        raise NotFound("Review not found.")
    if review.seller_reply:
        raise Conflict("You already replied.", code="already_replied")
    reply = (reply or "").strip()[:2000]
    if not reply:
        raise ValidationError(details={"reply": ["Required."]})
    _screen(reply, user)
    review.seller_reply = reply
    review.replied_at = timezone.now()
    review.save(update_fields=["seller_reply", "replied_at", "updated_at"])
    return review


def disputes_queue(user: Any) -> Any:
    if not can_mediate(user):
        raise PermissionDenied()
    return Order.objects.filter(status=S.DISPUTED).select_related("buyer", "seller").order_by("disputed_at")
