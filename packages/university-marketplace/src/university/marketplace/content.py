"""Content adapters for listings and reviews — moderatable, with an explicit policy.

**Listings** (scam listings, prohibited goods):

* *Who investigates*: the listing's scope moderators (e.g. a campus
  marketplace's), otherwise platform moderators.
* *Actions*: ``hide`` (seller-only; can't be republished), ``restore``, and
  ``remove`` (status removed; unpaid orders are cancelled and paid, unfinished
  orders are refunded in full). User-level sanctions apply to the seller.

**Reviews** (abuse, fake reviews):

* *Who investigates*: platform moderators.
* *Actions*: ``hide``/``restore``/``remove`` hide the review and recompute the
  seller's rating. Sanctions apply to the reviewer.

Order disputes are not moderation: mediators with
``marketplace.disputes.resolve`` decide them.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.core.content import ContentAdapter, ContentRef
from university.core.events import publish
from university.core.ids import is_valid_uuid
from university.marketplace import events
from university.marketplace.constants import LISTING_CONTENT_TYPE, REVIEW_CONTENT_TYPE, ListingStatus


class ListingAdapter(ContentAdapter):
    content_type = LISTING_CONTENT_TYPE
    label = "Marketplace listing"
    moderatable = True

    def iter_ids(self) -> Any:
        """Live items, for search backfills."""
        from university.marketplace.models import Listing

        qs = Listing.objects.filter(status__in=[ListingStatus.ACTIVE, ListingStatus.SOLD_OUT], hidden_at__isnull=True)
        return (str(pk) for pk in qs.values_list("pk", flat=True).iterator())

    def _get(self, object_id: Any) -> Any:
        from university.marketplace.models import Listing

        return Listing.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        listing = self._get(object_id)
        if listing is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(listing.pk),
            author_id=str(listing.seller_id),
            scope=listing.listing_scope,
            excerpt=f"{listing.title}\n{listing.description}"[:500],
            status="hidden" if listing.hidden_at else listing.status,
            created_at=listing.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        from university.marketplace.selectors import can_view_listing

        listing = self._get(object_id)
        return listing is not None and can_view_listing(viewer, listing)

    def hide(self, object_id: Any, *, reason: str) -> None:
        listing = self._get(object_id)
        if listing is not None and listing.hidden_at is None:
            listing.hidden_at = timezone.now()
            listing.hidden_reason = reason[:255]
            listing.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])
            publish(events.LISTING_HIDDEN, {"listing_id": listing.pk, "seller_id": listing.seller_id})

    def restore(self, object_id: Any) -> None:
        listing = self._get(object_id)
        if listing is not None and listing.hidden_at is not None:
            listing.hidden_at = None
            listing.hidden_reason = ""
            listing.save(update_fields=["hidden_at", "hidden_reason", "updated_at"])

    @transaction.atomic
    def remove(self, object_id: Any, *, reason: str) -> None:
        from university.core.payables import REFUND_REQUESTED
        from university.marketplace.constants import ORDER_PURPOSE, OrderStatus, PaymentMethod
        from university.marketplace.services import _close, _payload, _restock

        listing = self._get(object_id)
        if listing is None:
            return
        listing.status = ListingStatus.REMOVED
        listing.hidden_at = listing.hidden_at or timezone.now()
        listing.hidden_reason = reason[:255]
        listing.save(update_fields=["status", "hidden_at", "hidden_reason", "updated_at"])
        open_statuses = [
            OrderStatus.PENDING_PAYMENT,
            OrderStatus.PLACED,
            OrderStatus.PAID,
            OrderStatus.FULFILLED,
            OrderStatus.DISPUTED,
        ]
        for order in listing.orders.select_for_update().filter(status__in=open_statuses):
            paid = order.status != OrderStatus.PENDING_PAYMENT and order.status != OrderStatus.PLACED
            _restock(order)
            _close(order, OrderStatus.CANCELLED, cancelled_at=timezone.now(), cancel_reason="listing_removed")
            if paid and order.payment_method == PaymentMethod.ONLINE and order.total_minor:
                publish(
                    REFUND_REQUESTED, {"purpose": ORDER_PURPOSE, "object_id": order.pk, "reason": "Listing removed"}
                )
            publish(events.ORDER_CANCELLED, _payload(order, cancelled_by="moderators"))


class ReviewAdapter(ContentAdapter):
    content_type = REVIEW_CONTENT_TYPE
    label = "Seller review"
    moderatable = True

    def _get(self, object_id: Any) -> Any:
        from university.marketplace.models import Review

        return Review.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None

    def resolve(self, object_id: Any) -> ContentRef | None:
        review = self._get(object_id)
        if review is None:
            return None
        return ContentRef(
            content_type=self.content_type,
            object_id=str(review.pk),
            author_id=str(review.reviewer_id) if review.reviewer_id else None,
            excerpt=f"{review.rating}★ {review.comment}"[:500],
            status="hidden" if review.hidden_at else "published",
            created_at=review.created_at,
        )

    def can_view(self, viewer: Any, object_id: Any) -> bool:
        review = self._get(object_id)
        return review is not None and review.hidden_at is None

    def _set_hidden(self, object_id: Any, hidden: bool) -> None:
        from university.marketplace.services import _recompute_rating

        review = self._get(object_id)
        if review is None:
            return
        review.hidden_at = timezone.now() if hidden else None
        review.save(update_fields=["hidden_at", "updated_at"])
        _recompute_rating(review.seller_id)

    def hide(self, object_id: Any, *, reason: str) -> None:
        self._set_hidden(object_id, True)

    def restore(self, object_id: Any) -> None:
        self._set_hidden(object_id, False)

    def remove(self, object_id: Any, *, reason: str) -> None:
        self._set_hidden(object_id, True)
