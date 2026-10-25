"""Task registration (autodiscovered by Core): import every task so workers know them."""

from university.search.indexing import index_item, remove_item

__all__ = ["index_item", "remove_item"]
