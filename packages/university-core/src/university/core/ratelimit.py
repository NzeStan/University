"""Distributed, cache-backed rate limiting.

Counters live in the Django cache, so limits hold across any number of
application servers when the cache is shared (Redis). The algorithm is a
fixed window using atomic ``add`` + ``incr`` — no read-modify-write races.

Rates come from ``UNIVERSITY["THROTTLE_RATES"]`` and are used by both the DRF
throttle (:mod:`university.core.api.throttling`) and services::

    from university.core.ratelimit import rate_limit

    rate_limit("anonymous_post", key=str(user.pk))   # raises RateLimited
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass

from django.core.cache import caches

from university.core.conf import university_settings
from university.core.crypto import sha256_hex
from university.core.exceptions import RateLimited

_UNITS = {
    "s": 1,
    "sec": 1,
    "second": 1,
    "m": 60,
    "min": 60,
    "minute": 60,
    "h": 3600,
    "hour": 3600,
    "d": 86400,
    "day": 86400,
}
_RATE_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d*)\s*([a-z]+)\s*$")


def parse_rate(rate: str) -> tuple[int, int]:
    """Parse ``"10/min"`` or ``"100/15min"`` into ``(limit, period_seconds)``."""
    match = _RATE_RE.match(rate.lower())
    if not match:
        raise ValueError(f"Invalid rate {rate!r}.")
    limit, multiplier, unit = match.groups()
    unit = unit.rstrip("s") if unit not in _UNITS else unit
    if unit not in _UNITS:
        raise ValueError(f"Invalid rate unit in {rate!r}.")
    return int(limit), int(multiplier or 1) * _UNITS[unit]


@dataclass(frozen=True)
class RateLimitResult:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int


def get_rate(scope: str) -> str | None:
    """Configured rate for ``scope``: deployment settings, then module defaults."""
    rates = university_settings.get("THROTTLE_RATES", {}) or {}
    if scope in rates:
        return rates[scope]
    from university.core.registry import registry

    return registry.throttle_rates.get(scope)


class RateLimiter:
    def __init__(self, cache_alias: str | None = None) -> None:
        self.cache_alias = cache_alias

    @property
    def cache(self):  # type: ignore[no-untyped-def]
        return caches[self.cache_alias or university_settings.get("CACHE.ALIAS", "default")]

    def _key(self, scope: str, key: str, window: int) -> str:
        prefix = university_settings.get("CACHE.KEY_PREFIX", "university")
        return f"{prefix}:rl:{scope}:{sha256_hex(key)[:32]}:{window}"

    def hit(self, scope: str, key: str, *, rate: str | None = None, cost: int = 1) -> RateLimitResult:
        """Record ``cost`` hits and report whether the caller is within the limit."""
        rate = rate if rate is not None else get_rate(scope)
        if not rate:
            return RateLimitResult(True, 0, 0, 0)
        limit, period = parse_rate(rate)
        now = time.time()
        window = int(now // period)
        retry_after = max(1, int((window + 1) * period - now))
        cache_key = self._key(scope, key, window)
        cache = self.cache
        cache.add(cache_key, 0, timeout=period + 1)
        try:
            count = cache.incr(cache_key, cost)
        except ValueError:  # expired between add() and incr()
            cache.set(cache_key, cost, timeout=period + 1)
            count = cost
        return RateLimitResult(count <= limit, limit, max(0, limit - count), retry_after)

    def peek(self, scope: str, key: str, *, rate: str | None = None) -> int:
        rate = rate if rate is not None else get_rate(scope)
        if not rate:
            return 0
        _, period = parse_rate(rate)
        window = int(time.time() // period)
        return int(self.cache.get(self._key(scope, key, window), 0) or 0)

    def reset(self, scope: str, key: str, *, rate: str | None = None) -> None:
        rate = rate if rate is not None else get_rate(scope)
        if not rate:
            return
        _, period = parse_rate(rate)
        window = int(time.time() // period)
        self.cache.delete(self._key(scope, key, window))


limiter = RateLimiter()


def rate_limit(scope: str, *, key: str, rate: str | None = None, cost: int = 1) -> RateLimitResult:
    """Count a hit and raise :class:`RateLimited` when over the limit."""
    result = limiter.hit(scope, key, rate=rate, cost=cost)
    if not result.allowed:
        raise RateLimited(retry_after=result.retry_after)
    return result
