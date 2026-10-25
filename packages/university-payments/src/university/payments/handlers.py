"""Act on requests from selling modules, delivered as events (no imports either way)."""

from __future__ import annotations

from university.core.events import Event
from university.core.payables import REFUND_REQUESTED, RELEASE_REQUESTED


def on_release_requested(event: Event) -> None:
    from university.payments.services import release_for

    p = event.payload
    release_for(str(p.get("purpose")), p.get("object_id"))


def on_refund_requested(event: Event) -> None:
    from university.payments.services import refund_for

    p = event.payload
    amount = p.get("amount_minor")
    refund_for(
        str(p.get("purpose")),
        p.get("object_id"),
        amount_minor=int(amount) if amount else None,
        reason=str(p.get("reason") or "")[:255],
    )


HANDLERS = {RELEASE_REQUESTED: on_release_requested, REFUND_REQUESTED: on_refund_requested}
