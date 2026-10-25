"""Task registration (autodiscovered by Core): import every task so workers know them."""

from university.creator.services.accounts import sync_linked_accounts

__all__ = ["sync_linked_accounts"]
