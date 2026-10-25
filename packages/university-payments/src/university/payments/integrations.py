"""Core hook implementations: export and purge.

Financial records are kept on purge (tax and anti-fraud obligations): the
person is detached from them instead, and payout destinations are erased.
"""

from __future__ import annotations

from typing import Any


def export_data(user: Any) -> dict[str, Any]:
    from university.payments.ledger import payee_balances
    from university.payments.models import PaymentIntent, Payout

    return {
        "payments": [
            {
                "reference": i.reference,
                "purpose": i.purpose,
                "description": i.description,
                "amount_minor": i.amount_minor,
                "currency": i.currency,
                "status": i.status,
                "amount_refunded_minor": i.amount_refunded_minor,
                "created_at": i.created_at.isoformat(),
            }
            for i in PaymentIntent.objects.filter(payer=user)
        ],
        "payouts": [
            {
                "amount_minor": p.amount_minor,
                "currency": p.currency,
                "status": p.status,
                "created_at": p.created_at.isoformat(),
            }
            for p in Payout.objects.filter(payee=user)
        ],
        "balances": payee_balances(user.pk),
    }


def purge(user_id: Any) -> None:
    from university.payments.constants import IntentStatus
    from university.payments.models import PaymentIntent, Payout

    PaymentIntent.objects.filter(payer_id=user_id, status=IntentStatus.PENDING).update(
        status=IntentStatus.CANCELLED, failure_reason="account_deleted"
    )
    PaymentIntent.objects.filter(payer_id=user_id).update(payer=None, metadata={})
    Payout.objects.filter(payee_id=user_id).update(destination="(erased)")
