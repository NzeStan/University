"""Payable adapters: how modules sell things without depending on payments.

A module that charges for something (an event ticket, a marketplace order, a
creator's fee) describes it with a :class:`PayableAdapter`, contributed from
its AppConfig::

    class EventsConfig(UniversityAppConfig):
        def get_payable_adapters(self):
            return [RegistrationPayable()]

A payments module resolves adapters through Core by *purpose*
(``"events.registration"``) and never imports the selling module; the selling
module never imports payments. The adapter:

* :meth:`resolve` — says what is owed *now* by this payer (and refuses when
  nothing is payable: wrong person, already paid, hold expired …);
* :meth:`on_paid` — fulfils after a verified payment. Raising
  :class:`~university.core.exceptions.Conflict` means "too late, can't
  fulfil" and the payments module refunds automatically;
* :meth:`on_refunded` — reacts to refunds (optional).

Amounts are integers in minor units (kobo, pesewas, cents).

Selling modules ask payments to act through events, again without imports:
``payments.release.requested`` (release escrowed funds to the payee) and
``payments.refund.requested`` (refund the buyer), each with ``purpose`` and
``object_id``.
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

from university.core.exceptions import NotFound

RELEASE_REQUESTED = "payments.release.requested"
REFUND_REQUESTED = "payments.refund.requested"


@dataclass(frozen=True)
class Payable:
    purpose: str
    object_id: str
    payer_id: str
    amount_minor: int
    currency: str
    description: str
    #: Who ultimately receives the money (a seller, a creator), if not the platform.
    payee_id: str | None = None
    #: The platform's share of ``amount_minor`` (minor units).
    platform_fee_minor: int = 0
    #: Hold the payee's share until ``payments.release.requested``.
    escrow: bool = False
    #: Don't take payment after this (e.g. a ticket hold).
    expires_at: dt.datetime | None = None
    #: Ids and enum values only; passed to the provider as metadata.
    metadata: dict[str, Any] = field(default_factory=dict)


class PayableAdapter:
    purpose: str = ""
    label: str = ""

    def resolve(self, object_id: Any, payer: Any) -> Payable:
        raise NotImplementedError

    def on_paid(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        raise NotImplementedError

    def on_refunded(self, object_id: Any, *, reference: str, amount_minor: int, currency: str) -> None:
        """Called after a refund succeeds (full or partial)."""


def get_payable_adapter(purpose: str) -> PayableAdapter:
    from university.core.registry import registry

    adapter = registry.payable_adapters.get(purpose)
    if adapter is None:
        raise NotFound("Unknown payment purpose.")
    return adapter


def payable_purposes() -> list[str]:
    from university.core.registry import registry

    return sorted(registry.payable_adapters)


__all__ = [
    "REFUND_REQUESTED",
    "RELEASE_REQUESTED",
    "Payable",
    "PayableAdapter",
    "get_payable_adapter",
    "payable_purposes",
]
