"""DRF throttles backed by the distributed rate limiter.

* :class:`ScopedRateThrottle` — throttles views that set ``throttle_scope``
  (per user when authenticated, per client IP otherwise). Rates come from
  ``UNIVERSITY["THROTTLE_RATES"]``.
* :class:`GlobalRateThrottle` — a coarse ceiling on every request
  (``anon_global`` / ``user_global``) against abusive clients.

Unlike DRF's built-in throttles these use atomic cache counters, so they
remain correct across many application servers.
"""

from __future__ import annotations

from typing import Any

from rest_framework.throttling import BaseThrottle

from university.core.http import get_client_ip
from university.core.ratelimit import get_rate, limiter


def _identity(request: Any) -> str:
    user = getattr(request, "user", None)
    if user is not None and user.is_authenticated:
        return f"user:{user.pk}"
    return f"ip:{get_client_ip(request) or 'unknown'}"


class _LimiterThrottle(BaseThrottle):
    _retry_after: int | None = None

    def _check(self, scope: str, key: str) -> bool:
        result = limiter.hit(scope, key)
        self._retry_after = result.retry_after
        return result.allowed

    def wait(self) -> float | None:
        return self._retry_after


class ScopedRateThrottle(_LimiterThrottle):
    scope_attr = "throttle_scope"

    def allow_request(self, request: Any, view: Any) -> bool:
        scope = getattr(view, self.scope_attr, None)
        if callable(scope):
            scope = scope(request)
        if not scope or not get_rate(scope):
            return True
        return self._check(scope, _identity(request))


class GlobalRateThrottle(_LimiterThrottle):
    def allow_request(self, request: Any, view: Any) -> bool:
        user = getattr(request, "user", None)
        scope = "user_global" if user is not None and user.is_authenticated else "anon_global"
        if not get_rate(scope):
            return True
        return self._check(scope, _identity(request))
