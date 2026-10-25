from __future__ import annotations

from django.db import models
from django.utils.translation import gettext_lazy as _

LISTING_CONTENT_TYPE = "marketplace.listing"
REVIEW_CONTENT_TYPE = "marketplace.review"
ORDER_PURPOSE = "marketplace.order"


class Condition(models.TextChoices):
    NEW = "new", _("New")
    LIKE_NEW = "like_new", _("Like new")
    USED = "used", _("Used")
    FOR_PARTS = "for_parts", _("For parts")
    #: Services and digital goods.
    NOT_APPLICABLE = "not_applicable", _("Not applicable")


class ListingStatus(models.TextChoices):
    DRAFT = "draft", _("Draft")
    ACTIVE = "active", _("Active")
    PAUSED = "paused", _("Paused")
    SOLD_OUT = "sold_out", _("Sold out")
    #: Removed by the seller or by moderators.
    REMOVED = "removed", _("Removed")


class ListingVisibility(models.TextChoices):
    PUBLIC = "public", _("Everyone")
    #: Only members of the listing's scope (e.g. a campus marketplace).
    AUDIENCE = "audience", _("Members only")


class Fulfilment(models.TextChoices):
    PICKUP = "pickup", _("Pickup")
    DELIVERY = "delivery", _("Delivery")


class PaymentMethod(models.TextChoices):
    #: Paid through the payments module and held in escrow.
    ONLINE = "online", _("Online (protected)")
    #: Paid in person at pickup; no buyer protection.
    CASH_ON_PICKUP = "cash_on_pickup", _("Cash on pickup")


class DisputeOutcome(models.TextChoices):
    REFUND = "refund", _("Refund the buyer")
    RELEASE = "release", _("Release to the seller")


class OrderStatus(models.TextChoices):
    PENDING_PAYMENT = "pending_payment", _("Awaiting payment")
    #: Cash on pickup: reserved, waiting for the handover.
    PLACED = "placed", _("Placed")
    PAID = "paid", _("Paid")
    #: Shipped or ready for pickup.
    FULFILLED = "fulfilled", _("Fulfilled")
    COMPLETED = "completed", _("Completed")
    CANCELLED = "cancelled", _("Cancelled")
    DISPUTED = "disputed", _("Disputed")
    REFUNDED = "refunded", _("Refunded")


#: Orders still holding stock and not yet finished.
OPEN_ORDER_STATUSES = frozenset(
    {OrderStatus.PENDING_PAYMENT, OrderStatus.PLACED, OrderStatus.PAID, OrderStatus.FULFILLED, OrderStatus.DISPUTED}
)
