"""Read-side rules for listings, orders and sellers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.db.models import Q, QuerySet

from university.core.audiences import is_member, member_scopes
from university.core.exceptions import NotFound
from university.core.hooks import Hook, hooks
from university.core.ids import is_valid_uuid
from university.marketplace.constants import ListingStatus, ListingVisibility
from university.marketplace.models import Listing, MarketCategory, Order
from university.permissions.services import has_permission

BROWSABLE = (ListingStatus.ACTIVE, ListingStatus.SOLD_OUT)


def _authenticated(user: Any) -> bool:
    return bool(getattr(user, "is_authenticated", False))


def not_blocked(viewer: Any, other: Any) -> bool:
    if not _authenticated(viewer) or other is None:
        return True
    return hooks.allows(Hook.USER_CAN_INTERACT, viewer, other, "marketplace")


def can_view_listing(viewer: Any, listing: Listing) -> bool:
    if listing.deleted_at is not None:
        return False
    if _authenticated(viewer) and viewer.pk == listing.seller_id:
        return True
    if listing.status not in BROWSABLE or listing.hidden_at is not None:
        return False
    if listing.visibility == ListingVisibility.AUDIENCE and not is_member(viewer, listing.scope_type, listing.scope_id):
        return False
    return not_blocked(viewer, listing.seller)


def get_listing(listing_id: Any) -> Listing:
    listing = (
        Listing.objects.select_related("seller", "category").filter(pk=listing_id).first()
        if is_valid_uuid(listing_id)
        else None
    )
    if listing is None:
        raise NotFound("Listing not found.")
    return listing


def get_visible_listing(viewer: Any, listing_id: Any) -> Listing:
    listing = get_listing(listing_id)
    if not can_view_listing(viewer, listing):
        raise NotFound("Listing not found.")
    return listing


def _category_keys(key: str) -> list[str]:
    keys = [key]
    frontier = [key]
    while frontier:
        children = list(MarketCategory.objects.filter(parent__key__in=frontier).values_list("key", flat=True))
        keys += children
        frontier = children
    return keys


def browse(viewer: Any, params: Mapping[str, Any]) -> QuerySet[Listing]:
    scopes = member_scopes(viewer) if _authenticated(viewer) else frozenset()
    audience = Q(visibility=ListingVisibility.PUBLIC)
    for scope_type, scope_id in scopes:
        audience |= Q(visibility=ListingVisibility.AUDIENCE, scope_type=scope_type, scope_id=str(scope_id))
    qs = (
        Listing.objects.filter(status__in=BROWSABLE, hidden_at__isnull=True)
        .filter(audience)
        .select_related("seller", "category")
        .prefetch_related("images")
    )
    if q := (params.get("q") or "").strip()[:100]:
        qs = qs.filter(Q(title__icontains=q) | Q(description__icontains=q))
    if category := params.get("category"):
        qs = qs.filter(category__key__in=_category_keys(category))
    for field in ("condition", "currency"):
        if value := params.get(field):
            qs = qs.filter(**{field: value})
    if city := params.get("city"):
        qs = qs.filter(city__iexact=city)
    if params.get("scope_type") and params.get("scope_id"):
        qs = qs.filter(scope_type=params["scope_type"], scope_id=str(params["scope_id"]))
    if seller := params.get("seller"):
        qs = qs.filter(seller_id=seller) if is_valid_uuid(seller) else qs.none()
    for name, lookup in (("min_price", "price_minor__gte"), ("max_price", "price_minor__lte")):
        try:
            if params.get(name) not in (None, ""):
                qs = qs.filter(**{lookup: int(params[name])})
        except ValueError:
            pass
    if str(params.get("in_stock", "")).lower() in ("1", "true"):
        qs = qs.filter(status=ListingStatus.ACTIVE)
    order = {"price": ("price_minor", "-published_at"), "-price": ("-price_minor", "-published_at")}.get(
        params.get("sort", ""), ("-published_at", "id")
    )
    return qs.order_by(*order)


def can_mediate(user: Any) -> bool:
    return has_permission(user, "marketplace.disputes.resolve")


def get_order_for(user: Any, order_id: Any) -> Order:
    order = (
        Order.objects.select_related("buyer", "seller", "listing").filter(pk=order_id).first()
        if is_valid_uuid(order_id)
        else None
    )
    if order is None or not (
        _authenticated(user) and (user.pk in (order.buyer_id, order.seller_id) or can_mediate(user))
    ):
        raise NotFound("Order not found.")
    return order


def my_orders(user: Any, role: str) -> QuerySet[Order]:
    field = "seller" if role == "seller" else "buyer"
    return Order.objects.filter(**{field: user}).select_related("buyer", "seller").order_by("-created_at")
