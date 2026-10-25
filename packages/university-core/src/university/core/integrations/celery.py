"""Celery integration.

A single generic Celery task executes any registered University task by name,
so modules never import Celery directly. Make sure your Celery app loads
Django settings (``app.config_from_object("django.conf:settings",
namespace="CELERY")``) and that this module is imported by the worker; Core
imports it automatically when ``TASKS.BACKEND`` is the Celery backend.
"""

from __future__ import annotations

from typing import Any

from celery import shared_task

from university.core.tasks import run_task


@shared_task(name="university.core.run_task", acks_late=True, ignore_result=True)
def run_university_task(name: str, args: list[Any], kwargs: dict[str, Any]) -> None:
    run_task(name, args, kwargs)
