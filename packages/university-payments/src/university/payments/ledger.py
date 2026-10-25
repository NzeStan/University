"""Double-entry ledger postings and balances.

Accounts:

* ``provider:<key>`` — money held at a payment provider (asset; debit-positive).
* ``platform:revenue`` — platform income (fees, or the whole amount when there's no payee).
* ``payee:<user>:held`` — a payee's escrowed share, waiting for release.
* ``payee:<user>:available`` — a payee's withdrawable balance.
* ``payee:<user>:payout`` — balance committed to requested payouts.
* ``platform:payouts`` — money paid out to payees.

Liability and income accounts carry credit (negative) balances; balances are
reported positive for people.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from typing import Any

from django.db.models import Sum

from university.payments.constants import (
    PLATFORM_PAYOUTS,
    PLATFORM_REVENUE,
    EntryKind,
    payee_account,
    provider_account,
)
from university.payments.models import LedgerEntry, PaymentIntent, Payout, Refund


class UnbalancedPosting(Exception):
    pass


def post(
    legs: Iterable[tuple[str, int]],
    *,
    currency: str,
    kind: str,
    intent: PaymentIntent | None = None,
    refund: Refund | None = None,
    payout: Payout | None = None,
) -> uuid.UUID:
    legs = [(account, amount) for account, amount in legs if amount]
    if sum(amount for _, amount in legs) != 0:
        raise UnbalancedPosting(f"Posting does not balance: {legs}")
    group = uuid.uuid4()
    LedgerEntry.objects.bulk_create(
        [
            LedgerEntry(
                group=group,
                account=account,
                amount_minor=amount,
                currency=currency,
                kind=kind,
                intent=intent,
                refund=refund,
                payout=payout,
            )
            for account, amount in legs
        ]
    )
    return group


def _payee_share(intent: PaymentIntent, amount: int) -> int:
    """The payee's portion of ``amount`` (fees are taken proportionally)."""
    if not intent.payee_id or not intent.amount_minor:
        return 0
    net = intent.amount_minor - intent.platform_fee_minor
    return amount * net // intent.amount_minor


def record_payment(intent: PaymentIntent) -> None:
    amount = intent.amount_minor
    legs: list[tuple[str, int]] = [(provider_account(intent.provider), amount)]
    if intent.payee_id:
        share = _payee_share(intent, amount)
        bucket = "held" if intent.escrow else "available"
        legs += [(payee_account(intent.payee_id, bucket), -share), (PLATFORM_REVENUE, -(amount - share))]
    else:
        legs.append((PLATFORM_REVENUE, -amount))
    post(legs, currency=intent.currency, kind=EntryKind.PAYMENT, intent=intent)


def record_release(intent: PaymentIntent) -> int:
    """Move the payee's escrowed share (net of refunds so far) to available."""
    held = balance(payee_account(intent.payee_id, "held"), intent.currency, intent=intent)
    if held <= 0:
        return 0
    post(
        [(payee_account(intent.payee_id, "held"), held), (payee_account(intent.payee_id, "available"), -held)],
        currency=intent.currency,
        kind=EntryKind.RELEASE,
        intent=intent,
    )
    return held


def record_refund(refund: Refund) -> None:
    intent = refund.intent
    amount = refund.amount_minor
    legs: list[tuple[str, int]] = [(provider_account(intent.provider), -amount)]
    if intent.payee_id:
        share = _payee_share(intent, amount)
        bucket = "held" if intent.escrow and intent.released_at is None else "available"
        legs += [(payee_account(intent.payee_id, bucket), share), (PLATFORM_REVENUE, amount - share)]
    else:
        legs.append((PLATFORM_REVENUE, amount))
    post(legs, currency=intent.currency, kind=EntryKind.REFUND, intent=intent, refund=refund)


def record_payout(payout: Payout, kind: str) -> None:
    available = payee_account(payout.payee_id, "available")
    committed = payee_account(payout.payee_id, "payout")
    amount = payout.amount_minor
    legs = {
        EntryKind.PAYOUT_REQUESTED: [(available, amount), (committed, -amount)],
        EntryKind.PAYOUT_PAID: [(committed, amount), (PLATFORM_PAYOUTS, -amount)],
        EntryKind.PAYOUT_REVERSED: [(committed, amount), (available, -amount)],
    }[kind]
    post(legs, currency=payout.currency, kind=kind, payout=payout)


def balance(account: str, currency: str, *, intent: Any = None) -> int:
    """The account's balance as a positive amount owed (credit balances are flipped)."""
    qs = LedgerEntry.objects.filter(account=account, currency=currency)
    if intent is not None:
        qs = qs.filter(intent=intent)
    total = qs.aggregate(total=Sum("amount_minor"))["total"] or 0
    return -total if not account.startswith("provider:") else total


def payee_balances(user_id: Any) -> list[dict[str, Any]]:
    prefix = f"payee:{user_id}:"
    rows = (
        LedgerEntry.objects.filter(account__startswith=prefix)
        .values("account", "currency")
        .annotate(total=Sum("amount_minor"))
    )
    out: dict[str, dict[str, Any]] = {}
    for row in rows:
        bucket = row["account"][len(prefix) :]
        entry = out.setdefault(row["currency"], {"currency": row["currency"], "held": 0, "available": 0, "payout": 0})
        entry[bucket] = -row["total"]
    return sorted(out.values(), key=lambda r: r["currency"])
