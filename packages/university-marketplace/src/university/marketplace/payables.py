"""Online orders, sold through Core's payable contract (no payments import).

The seller's share is held in escrow and released when the order completes
(buyer confirmation, automatic completion, or a mediator's decision). If an
order expired before the payment arrived, :meth:`on_paid` raises ``Conflict``
and the payments module refunds the buyer automatically.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction

from university.core.exceptions import Conflict, NotFound
from university.core.ids import is_valid_uuid
from university.core.payables import Payable, PayableAdapter
from university.marketplace.constants import ORDER_PURPOSE, OrderStatus, PaymentMethod
from university.marketplace.models import Order


class OrderPayable(PayableAdapter):
    purpose = ORDER_PURPOSE
    label = "Marketplace order"

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        order = Order.objects.filter(pk=object_id).first() if is_valid_uuid(object_id) else None
        if order is None or order.buyer_id != payer.pk:
            raise NotFound("Order not found.")
        if order.status != OrderStatus.PENDING_PAYMENT or order.payment_method != PaymentMethod.ONLINE:
            raise Conflict("This order isn't awaiting payment.", code="not_awaiting_payment")
        return Payable(
            purpose=ORDER_PURPOSE,
            object_id=str(order.pk),
            payer_id=str(payer.pk),
            amount_minor=order.total_minor,
            currency=order.currency,
            description=f"{order.title} (x{order.quantity})"[:200],
            payee_id=str(order.seller_id) if order.seller_id else None,
            platform_fee_minor=order.platform_fee_minor,
            escrow=True,
            expires_at=order.expires_at,
            metadata={"order_reference": order.reference},
        )

    @transaction.atomic
    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        from university.marketplace.services import mark_paid

        mark_paid(object_id, reference=reference, amount_minor=amount_minor, currency=currency)

    @transaction.atomic
    def on_refunded(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        from university.marketplace.services import mark_refunded

        if Order.objects.filter(pk=object_id).exists():
            mark_refunded(object_id, amount_minor)
