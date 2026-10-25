"""Integration with Django's built-in tasks framework (Django 6.0+)."""

from __future__ import annotations

from typing import Any

from django.tasks import task as django_task

from university.core.tasks import run_task


@django_task
def run_university_task(name: str, args: list[Any], kwargs: dict[str, Any]) -> None:
    run_task(name, args, kwargs)
