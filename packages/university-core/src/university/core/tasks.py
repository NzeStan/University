"""Asynchronous task abstraction.

Modules define tasks with :func:`task` and enqueue them with :func:`enqueue`.
The execution backend is configured once per deployment::

    UNIVERSITY = {"TASKS": {"BACKEND": "university.core.tasks.CeleryTaskBackend"}}

Backends:

* :class:`ImmediateTaskBackend` — run in-process (development and tests).
* :class:`CeleryTaskBackend` — Celery, the first-class production backend.
* :class:`DjangoTaskBackend` — Django's built-in tasks framework (Django 6+).

Tasks are enqueued after the current transaction commits by default, so a
worker never observes uncommitted data. Arguments must be JSON-serialisable;
pass identifiers, not model instances.

Example::

    @task(name="users.send_verification_email")
    def send_verification_email(user_id: str) -> None: ...

    enqueue(send_verification_email, str(user.pk))
"""

from __future__ import annotations

import json
import logging
from collections.abc import Callable
from typing import Any, Protocol

from django.core.exceptions import ImproperlyConfigured
from django.db import transaction

from university.core.conf import university_settings

logger = logging.getLogger("university.tasks")

_TASKS: dict[str, Callable[..., Any]] = {}


def task(func: Callable[..., Any] | None = None, *, name: str | None = None) -> Any:
    """Register a function as a University task. Usable with or without args."""

    def decorator(fn: Callable[..., Any]) -> Callable[..., Any]:
        task_name = name or f"{fn.__module__}.{fn.__qualname__}"
        existing = _TASKS.get(task_name)
        if existing is not None and existing.__qualname__ != fn.__qualname__:
            raise ImproperlyConfigured(f"Duplicate University task name {task_name!r}.")
        _TASKS[task_name] = fn
        fn.task_name = task_name  # type: ignore[attr-defined]
        fn.enqueue = lambda *a, **kw: enqueue(task_name, *a, **kw)  # type: ignore[attr-defined]
        return fn

    return decorator(func) if func is not None else decorator


def get_task(name: str) -> Callable[..., Any]:
    try:
        return _TASKS[name]
    except KeyError:
        raise LookupError(f"Unknown University task {name!r}.") from None


def registered_tasks() -> list[str]:
    return sorted(_TASKS)


def run_task(name: str, args: list[Any], kwargs: dict[str, Any]) -> Any:
    """Execute a registered task. Called by every backend's worker entry point."""
    return get_task(name)(*args, **kwargs)


# ---------------------------------------------------------------- backends
class TaskBackend(Protocol):
    def enqueue(self, name: str, args: list[Any], kwargs: dict[str, Any], *, countdown: int | None = None) -> None: ...


class ImmediateTaskBackend:
    """Runs tasks synchronously in the calling process."""

    def enqueue(self, name: str, args: list[Any], kwargs: dict[str, Any], *, countdown: int | None = None) -> None:
        try:
            run_task(name, args, kwargs)
        except Exception:
            logger.exception("Task %s failed", name)
            if university_settings.get("TASKS.EAGER_PROPAGATE_EXCEPTIONS", False):
                raise


class CeleryTaskBackend:
    """Dispatches tasks to Celery through a single generic Celery task."""

    def __init__(self) -> None:
        try:
            from university.core.integrations import celery as _celery  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on extras
            raise ImproperlyConfigured(
                "CeleryTaskBackend requires Celery: pip install 'university-core[celery]'."
            ) from exc

    def enqueue(self, name: str, args: list[Any], kwargs: dict[str, Any], *, countdown: int | None = None) -> None:
        from university.core.integrations.celery import run_university_task

        options: dict[str, Any] = {}
        queue = university_settings.get("TASKS.QUEUES", {}).get(name)
        if queue:
            options["queue"] = queue
        if countdown:
            options["countdown"] = countdown
        run_university_task.apply_async(args=[name, args, kwargs], **options)


class DjangoTaskBackend:
    """Dispatches tasks through ``django.tasks`` (Django 6.0+)."""

    def __init__(self) -> None:
        try:
            from university.core.integrations import django_tasks as _dt  # noqa: F401
        except ImportError as exc:  # pragma: no cover - depends on Django version
            raise ImproperlyConfigured("DjangoTaskBackend requires Django 6.0 or newer.") from exc

    def enqueue(self, name: str, args: list[Any], kwargs: dict[str, Any], *, countdown: int | None = None) -> None:
        import datetime as dt

        from django.utils import timezone

        from university.core.integrations.django_tasks import run_university_task

        task_obj = run_university_task
        if countdown:
            task_obj = task_obj.using(run_after=timezone.now() + dt.timedelta(seconds=countdown))
        task_obj.enqueue(name, args, kwargs)


_backend_cache: dict[type, TaskBackend] = {}


def get_task_backend() -> TaskBackend:
    backend_cls = university_settings.import_from("TASKS.BACKEND")
    backend = _backend_cache.get(backend_cls)
    if backend is None:
        backend = backend_cls()
        _backend_cache[backend_cls] = backend
    return backend


def _ensure_json(args: tuple[Any, ...], kwargs: dict[str, Any], name: str) -> None:
    try:
        json.dumps([args, kwargs])
    except (TypeError, ValueError) as exc:
        raise TypeError(
            f"Arguments for task {name!r} must be JSON-serialisable (pass ids, not objects): {exc}"
        ) from exc


def schedule(
    task_ref: str | Callable[..., Any],
    args: tuple[Any, ...] = (),
    kwargs: dict[str, Any] | None = None,
    *,
    on_commit: bool = True,
    countdown: int | None = None,
) -> None:
    """Enqueue a task with explicit options."""
    name = task_ref if isinstance(task_ref, str) else getattr(task_ref, "task_name", None)
    if not name:
        raise ImproperlyConfigured(f"{task_ref!r} is not a registered University task.")
    get_task(name)
    kwargs = kwargs or {}
    _ensure_json(args, kwargs, name)

    def send() -> None:
        get_task_backend().enqueue(name, list(args), dict(kwargs), countdown=countdown)

    if on_commit:
        transaction.on_commit(send)
    else:
        send()


def enqueue(task_ref: str | Callable[..., Any], *args: Any, **kwargs: Any) -> None:
    """Enqueue a task after the current transaction commits."""
    schedule(task_ref, args, kwargs)


__all__ = [
    "CeleryTaskBackend",
    "DjangoTaskBackend",
    "ImmediateTaskBackend",
    "TaskBackend",
    "enqueue",
    "get_task",
    "registered_tasks",
    "run_task",
    "schedule",
    "task",
]
