"""Event-bus names published by the marketplace (payloads carry ids only).

Order events carry ``order_id``, ``buyer_id``, ``seller_id`` and ``status``.
"""

LISTING_PUBLISHED = "marketplace.listing.published"
LISTING_HIDDEN = "marketplace.listing.hidden"
ORDER_CREATED = "marketplace.order.created"
ORDER_PAID = "marketplace.order.paid"
ORDER_FULFILLED = "marketplace.order.fulfilled"
ORDER_COMPLETED = "marketplace.order.completed"
ORDER_CANCELLED = "marketplace.order.cancelled"
ORDER_REFUNDED = "marketplace.order.refunded"
ORDER_DISPUTED = "marketplace.order.disputed"
DISPUTE_RESOLVED = "marketplace.dispute.resolved"
REVIEW_CREATED = "marketplace.review.created"
