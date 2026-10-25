"""Read-side queries. Visibility rules live here, not in views."""

from __future__ import annotations

from typing import Any

from django.db.models import QuerySet

from university.__module__.models import Item


def items_for(user: Any) -> QuerySet[Item]:
    return Item.objects.filter(owner=user).order_by("-created_at", "-id")
