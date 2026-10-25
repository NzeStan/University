"""Task registration (autodiscovered by Core): import every task so workers know them."""

from university.marketplace.services import auto_complete_orders, expire_unpaid_orders

__all__ = ["auto_complete_orders", "expire_unpaid_orders"]
