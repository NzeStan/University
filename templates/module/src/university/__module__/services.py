"""Mutations. Every service authorises, validates, audits and publishes events."""

from __future__ import annotations

from typing import Any

from django.db import transaction

from university.__module__ import events
from university.__module__.conf import __module___settings
from university.__module__.models import Item
from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import NotFound, ValidationError
from university.permissions.services import authorize


@transaction.atomic
def create_item(*, actor: Any, title: str) -> Item:
    authorize(actor, "__module__.items.create")
    if Item.objects.filter(owner=actor).count() >= int(__module___settings.MAX_ITEMS_PER_USER):
        raise ValidationError("You have reached the maximum number of items.", code="item_limit")
    item = Item.objects.create(owner=actor, title=title.strip())
    audit("__module__.item.created", actor=actor, target=item)
    publish(events.ITEM_CREATED, {"item_id": item.pk, "owner_id": actor.pk}, actor=actor)
    return item


@transaction.atomic
def delete_item(*, actor: Any, item_id: Any) -> None:
    item = Item.objects.filter(pk=item_id, owner=actor).first()  # object-level ownership
    if item is None:
        raise NotFound()
    item.delete()  # soft delete
    audit("__module__.item.deleted", actor=actor, target=item)
    publish(events.ITEM_DELETED, {"item_id": item.pk, "owner_id": actor.pk}, actor=actor)
