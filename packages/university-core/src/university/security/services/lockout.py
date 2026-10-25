"""Brute-force protection for credential checks.

Three independent counters, all in the shared cache:

* identifier + IP — stops focused guessing from one source;
* identifier — stops distributed credential stuffing against one account;
* IP — stops password spraying across many accounts.

When a counter exceeds its threshold within the window, further attempts on
that key are refused for ``LOCKOUT_SECONDS`` without checking the password.
"""

from __future__ import annotations

import time
from typing import Any

from django.core.cache import caches

from university.core.conf import university_settings
from university.core.ratelimit import limiter


def _cfg() -> dict[str, Any]:
    return university_settings.get("AUTH.LOCKOUT")


def _cache() -> Any:
    return caches[university_settings.get("CACHE.ALIAS", "default")]


def _counters(identifier_hash: str, ip: str | None) -> list[tuple[str, str, int]]:
    cfg = _cfg()
    ip = ip or "unknown"
    return [
        ("lockout_ident_ip", f"{identifier_hash}:{ip}", int(cfg["MAX_FAILURES_PER_IDENTIFIER_AND_IP"])),
        ("lockout_ident", identifier_hash, int(cfg["MAX_FAILURES_PER_IDENTIFIER"])),
        ("lockout_ip", ip, int(cfg["MAX_FAILURES_PER_IP"])),
    ]


def _lock_key(scope: str, key: str) -> str:
    prefix = university_settings.get("CACHE.KEY_PREFIX", "university")
    return f"{prefix}:lock:{scope}:{key}"


def check_lockout(identifier_hash: str, ip: str | None) -> int | None:
    """Seconds until the caller may retry, or ``None`` when not locked."""
    if not _cfg().get("ENABLED", True):
        return None
    cache = _cache()
    now = time.time()
    for scope, key, _ in _counters(identifier_hash, ip):
        until = cache.get(_lock_key(scope, key))
        if until and float(until) > now:
            return max(1, int(float(until) - now))
    return None


def register_failure(identifier_hash: str, ip: str | None) -> bool:
    """Count a failure. Returns True if this failure triggered a lockout."""
    cfg = _cfg()
    if not cfg.get("ENABLED", True):
        return False
    window = int(cfg["WINDOW_SECONDS"])
    duration = int(cfg["LOCKOUT_SECONDS"])
    locked = False
    for scope, key, maximum in _counters(identifier_hash, ip):
        result = limiter.hit(scope, key, rate=f"{maximum}/{window}s")
        if result.remaining <= 0:  # the maximum-th failure locks
            _cache().set(_lock_key(scope, key), time.time() + duration, timeout=duration)
            locked = True
    return locked


def clear_failures(identifier_hash: str, ip: str | None) -> None:
    cfg = _cfg()
    window = int(cfg["WINDOW_SECONDS"])
    for scope, key, maximum in _counters(identifier_hash, ip)[:2]:
        limiter.reset(scope, key, rate=f"{maximum}/{window}s")
        _cache().delete(_lock_key(scope, key))
