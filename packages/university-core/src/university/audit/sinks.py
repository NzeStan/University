"""Audit sinks — where audit entries are written.

``DatabaseSink`` (default) persists :class:`~university.audit.models.AuditLog`
rows. ``LoggingSink`` additionally emits each entry as a structured log record
on the ``university.audit`` logger, for shipping to a SIEM or WORM store.
Configure with ``UNIVERSITY["AUDIT"]["SINKS"]``.
"""

from __future__ import annotations

import logging
from typing import Any, Protocol

from university.audit.models import AuditLog

logger = logging.getLogger("university.audit")


class AuditSink(Protocol):
    def write(self, entry: AuditLog) -> None: ...


class DatabaseSink:
    def write(self, entry: AuditLog) -> None:
        entry.save(force_insert=True)


class LoggingSink:
    def write(self, entry: AuditLog) -> None:
        content: dict[str, Any] = entry.hashable_content()
        content["entry_hash"] = entry.entry_hash
        logger.info("audit %s", entry.action, extra={"audit": content})
