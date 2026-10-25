"""Task registration (autodiscovered by Core): import every task so workers know them."""

from university.trending.services import compute_trending

__all__ = ["compute_trending"]
