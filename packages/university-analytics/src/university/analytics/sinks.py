"""Raw-event sinks for external analytics stores (spec: don't keep every event in the primary DB).

A sink receives a **minimised** event: its name, time (to the minute),
breakdown dimensions and a pseudonymous actor that changes every month (a
keyed hash), so a warehouse can count uniques without learning who anyone is
or tracking them across months. Payloads (which can contain user ids) are
never forwarded.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Protocol

logger = logging.getLogger("university.analytics.events")


class AnalyticsSink(Protocol):
    def emit(self, event: dict[str, Any]) -> None: ...


class LogSink:
    """Writes one JSON line per event to the ``university.analytics.events`` logger."""

    def emit(self, event: dict[str, Any]) -> None:
        logger.info(json.dumps(event, sort_keys=True, default=str))


_cache: dict[str, Any] = {}


def get_sinks() -> list[AnalyticsSink]:
    from django.utils.module_loading import import_string

    from university.analytics.conf import analytics_settings

    sinks = []
    for path in analytics_settings.get("SINKS") or []:
        if path not in _cache:
            _cache[path] = import_string(path)()
        sinks.append(_cache[path])
    return sinks
