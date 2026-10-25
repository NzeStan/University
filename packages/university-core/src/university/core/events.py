"""The internal event bus.

Modules communicate through events instead of importing each other::

    from university.core.events import publish, subscribe

    publish("post.created", {"post_id": post.pk}, actor=user)

    @subscribe("user.*")
    def on_user_event(event): ...

    @subscribe("post.reported", run_async=True)   # executed by the task backend
    def index_report(event): ...

Rules:

* Event names are lowercase dotted strings: ``<domain>.<entity>[.<verb>]``.
* Payloads are JSON (identifiers, not model instances) and never contain
  secrets or the identity behind anonymous content.
* Events are dispatched after the surrounding transaction commits (configurable),
  so handlers never react to rolled-back changes.
* A failing synchronous handler is logged and isolated from the publisher.

Every dispatched event is also sent as the Django signal
:data:`event_published` for code that prefers signals.
"""

from __future__ import annotations

import fnmatch
import logging
import re
import threading
import uuid
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction
from django.dispatch import Signal
from django.utils import timezone
from django.utils.module_loading import import_string

from university.core.conf import university_settings
from university.core.context import get_request_context
from university.core.serialization import to_jsonable
from university.core.tasks import task

logger = logging.getLogger("university.events")

#: Sent for every dispatched event with ``event=<Event>``.
event_published = Signal()

EVENT_NAME_RE = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")

EventHandler = Callable[["Event"], Any]


@dataclass(frozen=True)
class Event:
    name: str
    payload: Mapping[str, Any] = field(default_factory=dict)
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    occurred_at: str = field(default_factory=lambda: timezone.now().isoformat())
    actor_id: str | None = None
    request_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "payload": dict(self.payload),
            "id": self.id,
            "occurred_at": self.occurred_at,
            "actor_id": self.actor_id,
            "request_id": self.request_id,
        }

    @classmethod
    def from_dict(cls, data: Mapping[str, Any]) -> Event:
        return cls(
            name=data["name"],
            payload=data.get("payload") or {},
            id=data["id"],
            occurred_at=data["occurred_at"],
            actor_id=data.get("actor_id"),
            request_id=data.get("request_id"),
        )


@dataclass(frozen=True)
class _Subscription:
    pattern: str
    handler: EventHandler
    run_async: bool
    path: str | None


class EventBus:
    def __init__(self) -> None:
        self._subscriptions: list[_Subscription] = []
        self._async_paths: set[str] = set()
        self._lock = threading.Lock()

    # ------------------------------------------------------------ subscribe
    def subscribe(self, pattern: str, handler: EventHandler | None = None, *, run_async: bool = False) -> Any:
        """Subscribe ``handler`` to events matching ``pattern`` (fnmatch style)."""

        def decorator(fn: EventHandler) -> EventHandler:
            path: str | None = None
            if run_async:
                path = f"{fn.__module__}.{fn.__qualname__}"
                if "." in fn.__qualname__ or "<" in fn.__qualname__:
                    raise ImproperlyConfigured(f"Async event handlers must be module-level functions (got {path}).")
            with self._lock:
                if any(s.pattern == pattern and s.handler is fn for s in self._subscriptions):
                    return fn
                self._subscriptions.append(_Subscription(pattern, fn, run_async, path))
                if path:
                    self._async_paths.add(path)
            return fn

        return decorator(handler) if handler is not None else decorator

    def unsubscribe(self, pattern: str, handler: EventHandler) -> None:
        with self._lock:
            self._subscriptions = [
                s for s in self._subscriptions if not (s.pattern == pattern and s.handler is handler)
            ]

    def subscriptions(self, name: str) -> list[_Subscription]:
        return [s for s in self._subscriptions if fnmatch.fnmatchcase(name, s.pattern)]

    def is_registered_async_handler(self, path: str) -> bool:
        return path in self._async_paths

    # -------------------------------------------------------------- publish
    def publish(
        self,
        name: str,
        payload: Mapping[str, Any] | None = None,
        *,
        actor: Any = None,
        on_commit: bool | None = None,
    ) -> Event:
        if not EVENT_NAME_RE.match(name):
            raise ValueError(f"Invalid event name {name!r}.")
        actor_id = None
        if actor is not None and getattr(actor, "is_authenticated", True):
            actor_id = str(getattr(actor, "pk", actor))
        event = Event(
            name=name,
            payload=to_jsonable(dict(payload or {})),
            actor_id=actor_id,
            request_id=get_request_context().request_id,
        )
        if on_commit is None:
            on_commit = university_settings.get("EVENTS.DISPATCH_ON_COMMIT", True)
        if on_commit:
            transaction.on_commit(lambda: self.dispatch(event))
        else:
            self.dispatch(event)
        return event

    def dispatch(self, event: Event) -> None:
        raise_errors = university_settings.get("EVENTS.RAISE_HANDLER_ERRORS", False)
        try:
            event_published.send(sender=EventBus, event=event)
        except Exception:
            logger.exception("event_published receiver failed for %s", event.name)
            if raise_errors:
                raise
        for sub in self.subscriptions(event.name):
            try:
                if sub.run_async:
                    from university.core.tasks import enqueue

                    enqueue(run_async_handler, sub.path, event.to_dict())
                else:
                    sub.handler(event)
            except Exception:
                logger.exception("Event handler %r failed for %s", sub.handler, event.name)
                if raise_errors:
                    raise


#: The process-wide event bus.
event_bus = EventBus()

publish = event_bus.publish
subscribe = event_bus.subscribe


@task(name="university.core.events.run_async_handler")
def run_async_handler(handler_path: str, event_data: dict[str, Any]) -> None:
    # Only import handlers that were registered in this process, so a forged
    # queue message cannot make the worker import arbitrary code.
    if not event_bus.is_registered_async_handler(handler_path):
        logger.error("Refusing to run unregistered async event handler %s", handler_path)
        return
    handler = import_string(handler_path)
    handler(Event.from_dict(event_data))


__all__ = ["Event", "EventBus", "event_bus", "event_published", "publish", "subscribe"]
