"""Event handlers (subscribed in apps.py)."""

from __future__ import annotations

from university.__module__.models import Item
from university.core.events import Event


def on_user_deleted(event: Event) -> None:
    Item.objects.filter(owner_id=event.payload["user_id"]).delete()  # soft delete
