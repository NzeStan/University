"""Core hook implementations: seller badge, export and purge."""

from __future__ import annotations

from typing import Any


def public_profile(target: Any, viewer: Any) -> dict[str, Any]:
    from university.marketplace.models import SellerProfile

    profile = SellerProfile.objects.filter(user=target).first()
    if profile is None:
        return {}
    return {"seller": {"store_name": profile.store_name, "rating": profile.rating, "sales_count": profile.sales_count}}


def export_data(user: Any) -> dict[str, Any]:
    from university.marketplace.models import Listing, Order, Review

    def order_row(o: Order) -> dict[str, Any]:
        return {
            "reference": o.reference,
            "title": o.title,
            "total_minor": o.total_minor,
            "currency": o.currency,
            "status": o.status,
            "delivery_details": o.delivery_details,
            "created_at": o.created_at.isoformat(),
        }

    return {
        "marketplace_listings": [
            {"title": li.title, "price_minor": li.price_minor, "currency": li.currency, "status": li.status}
            for li in Listing.all_objects.filter(seller=user)
        ],
        "marketplace_purchases": [order_row(o) for o in Order.objects.filter(buyer=user)],
        "marketplace_sales": [
            {k: v for k, v in order_row(o).items() if k != "delivery_details"}
            for o in Order.objects.filter(seller=user)
        ],
        "marketplace_reviews_written": [
            {"rating": r.rating, "comment": r.comment, "created_at": r.created_at.isoformat()}
            for r in Review.objects.filter(reviewer=user)
        ],
    }


def purge(user_id: Any) -> None:
    """Remove listings and personal details; keep order records (counterparties and finance rely on them)."""
    from django.db import transaction
    from django.db.models import Q
    from django.utils import timezone

    from university.marketplace.constants import ListingStatus, OrderStatus
    from university.marketplace.models import Listing, Order, SellerProfile
    from university.marketplace.services import _close, _restock

    with transaction.atomic():
        Listing.objects.filter(seller_id=user_id).update(status=ListingStatus.REMOVED)
        # Unpaid orders by or to this person are cancelled.
        open_orders = Order.objects.select_for_update().filter(
            Q(buyer_id=user_id) | Q(seller_id=user_id), status__in=[OrderStatus.PENDING_PAYMENT, OrderStatus.PLACED]
        )
        for order in open_orders:
            _restock(order)
            _close(order, OrderStatus.CANCELLED, cancelled_at=timezone.now(), cancel_reason="account_deleted")
        Order.objects.filter(buyer_id=user_id).update(delivery_details="")
        Order.objects.filter(seller_id=user_id).update(delivery_details="")
        Listing.all_objects.filter(seller_id=user_id).update(description="", location_note="")
        SellerProfile.objects.filter(user_id=user_id).delete()
