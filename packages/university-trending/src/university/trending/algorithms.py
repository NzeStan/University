"""Trending algorithms (configurable: ``TRENDING.ALGORITHM``).

The default, :class:`GravityVelocity`, combines:

* **engagement** — weighted signals in the window (comments and shares count
  more than views; configurable ``WEIGHTS``), so raw like totals don't win;
* **velocity** — how fast engagement is arriving now compared with earlier in
  the window (rising items outrank old ones that plateaued);
* **recency** — gravity decay by the item's age;
* **breadth** — at least ``MIN_UNIQUE_ACTORS`` different people.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Protocol


@dataclass
class ItemStats:
    #: Weighted-signal inputs: ``{signal: count}`` over the whole window and the recent period.
    window: dict[str, int] = field(default_factory=dict)
    recent: dict[str, int] = field(default_factory=dict)
    unique_actors: int = 0
    age_hours: float = 0.0


class TrendingAlgorithm(Protocol):
    def score(self, stats: ItemStats) -> float: ...


class GravityVelocity:
    def __init__(self, settings: Any) -> None:
        self.weights: dict[str, float] = settings.get("WEIGHTS") or {}
        self.window_hours = float(settings.get("WINDOW_HOURS", 48))
        self.recent_hours = float(settings.get("VELOCITY_HOURS", 6))
        self.velocity_weight = float(settings.get("VELOCITY_WEIGHT", 1.0))
        self.gravity = float(settings.get("GRAVITY", 1.5))
        self.min_actors = int(settings.get("MIN_UNIQUE_ACTORS", 2))

    def _weighted(self, counts: dict[str, int]) -> float:
        return sum(self.weights.get(signal, 0.0) * count for signal, count in counts.items())

    def score(self, stats: ItemStats) -> float:
        if stats.unique_actors < self.min_actors:
            return 0.0
        engagement = self._weighted(stats.window)
        if engagement <= 0:
            return 0.0
        recent = self._weighted(stats.recent)
        earlier = engagement - recent
        recent_rate = recent / max(self.recent_hours, 1.0)
        earlier_rate = earlier / max(self.window_hours - self.recent_hours, 1.0)
        velocity = min((recent_rate + 0.1) / (earlier_rate + 0.1), 10.0)
        boost = 1.0 + self.velocity_weight * math.log1p(max(velocity - 1.0, 0.0))
        return engagement * boost / ((stats.age_hours + 2.0) ** self.gravity)


def get_algorithm() -> TrendingAlgorithm:
    from django.utils.module_loading import import_string

    from university.trending.conf import trending_settings

    return import_string(trending_settings.get("ALGORITHM"))(trending_settings)
