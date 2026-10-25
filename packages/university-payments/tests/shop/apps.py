"""A stand-in selling module (like marketplace or events) for tests."""

from __future__ import annotations

from typing import Any

from university.core.exceptions import Conflict, NotFound, PermissionDenied
from university.core.modules import UniversityAppConfig
from university.core.payables import Payable, PayableAdapter

#: id -> {"payer", "amount", "currency", "payee", "fee", "escrow", "expires_at", "too_late"}
ITEMS: dict[str, dict[str, Any]] = {}
PAID: list[tuple[str, str, int]] = []
REFUNDED: list[tuple[str, int]] = []


class ItemPayable(PayableAdapter):
    purpose = "shop.item"
    label = "Shop item"

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        item = ITEMS.get(str(object_id))
        if item is None:
            raise NotFound("Item not found.")
        if item["payer"] != str(payer.pk) and not item.get("lenient"):  # "lenient": a buggy adapter.
            raise PermissionDenied("Not yours to pay for.")
        return Payable(
            purpose=self.purpose,
            object_id=str(object_id),
            payer_id=item["payer"],
            amount_minor=item["amount"],
            currency=item.get("currency", "NGN"),
            description=f"Item {object_id}",
            payee_id=item.get("payee"),
            platform_fee_minor=item.get("fee", 0),
            escrow=item.get("escrow", False),
            expires_at=item.get("expires_at"),
        )

    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        if ITEMS[str(object_id)].get("too_late"):
            raise Conflict("Too late.", code="hold_expired")
        PAID.append((str(object_id), reference, amount_minor))

    def on_refunded(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        REFUNDED.append((str(object_id), amount_minor))


class ShopConfig(UniversityAppConfig):
    name = "tests.shop"
    label = "test_shop"
    module_name = "test_shop"

    def get_payable_adapters(self) -> list[Any]:
        return [ItemPayable()]
