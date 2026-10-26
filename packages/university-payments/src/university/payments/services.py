"""Payment services: checkout, verification, fulfilment, refunds, escrow and payouts.

Trust model:

* What is owed comes from the selling module's payable adapter, never the client.
* Whether something was paid comes from :meth:`PaymentProvider.verify`, never
  from a webhook body or a redirect. Amount and currency must match exactly.
* Every state change happens under a row lock on the intent and is idempotent,
  so webhook retries, duplicate redirects and concurrent workers are safe.
"""

from __future__ import annotations

import datetime as dt
import logging
import re
import secrets
from typing import Any

from django.contrib.auth import get_user_model
from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ProviderError, ValidationError
from university.core.payables import get_payable_adapter
from university.core.ratelimit import rate_limit
from university.core.tasks import task
from university.payments import events, ledger
from university.payments.conf import payments_settings
from university.payments.constants import PAID_STATUSES, EntryKind, IntentStatus, PayoutStatus, RefundStatus
from university.payments.models import PaymentIntent, Payout, Refund
from university.payments.providers import ProviderTransaction, WebhookNotice, get_provider
from university.permissions.services import authorize

logger = logging.getLogger("university.payments")


def _reference(prefix: str) -> str:
    return f"{prefix}-{secrets.token_hex(10).upper()}"


def _callback_url(reference: str, requested: str | None) -> str:
    if requested:
        allowed = payments_settings.get("ALLOWED_CALLBACK_PREFIXES") or []
        if not any(requested.startswith(prefix) for prefix in allowed):
            raise ValidationError(details={"callback_url": ["This return address isn't allowed."]})
        return requested
    return str(payments_settings.get("CALLBACK_URL")).format(reference=reference)


def _payload(intent: PaymentIntent, **extra: Any) -> dict[str, Any]:
    return {
        "intent_id": intent.pk,
        "reference": intent.reference,
        "purpose": intent.purpose,
        "object_id": intent.object_id,
        "payer_id": intent.payer_id,
        "payee_id": intent.payee_id,
        "amount_minor": intent.amount_minor,
        "currency": intent.currency,
        **extra,
    }


# ----------------------------------------------------------------- checkout
@transaction.atomic
def start_checkout(
    *, payer: Any, purpose: str, object_id: Any, provider: str | None = None, callback_url: str | None = None
) -> PaymentIntent:
    rate_limit("payments_checkout", key=str(payer.pk))
    adapter = get_payable_adapter(purpose)
    payable = adapter.resolve(object_id, payer)  # Authorises the payer and prices the item.
    if str(payable.payer_id) != str(payer.pk):
        raise PermissionDenied("You can't pay for this.")
    if payable.amount_minor <= 0:
        raise ValidationError("Nothing to pay.", code="nothing_to_pay")
    if payable.currency not in payments_settings.get("CURRENCIES", []):
        raise ValidationError("This currency isn't supported.", code="currency_unsupported")
    if not 0 <= payable.platform_fee_minor <= payable.amount_minor:
        raise ValidationError("Invalid platform fee.", code="invalid_fee")
    if not payer.email:
        raise ValidationError("Add an email address to pay.", code="email_required")
    provider_obj = get_provider(provider)
    now = timezone.now()
    ttl = now + dt.timedelta(minutes=int(payments_settings.get("INTENT_TTL_MINUTES", 60)))
    expires_at = min(ttl, payable.expires_at) if payable.expires_at else ttl
    existing = (
        PaymentIntent.objects.select_for_update()
        .filter(purpose=purpose, object_id=str(object_id), payer=payer, status=IntentStatus.PENDING)
        .first()
    )
    if existing is not None:
        same = (
            existing.amount_minor == payable.amount_minor
            and existing.currency == payable.currency
            and existing.provider == provider_obj.key
            and existing.expires_at > now
        )
        if same:
            return existing  # Retrying checkout reuses the open one.
        existing.status = IntentStatus.CANCELLED
        existing.failure_reason = "superseded"
        existing.save(update_fields=["status", "failure_reason", "updated_at"])
    intent = PaymentIntent(
        reference=_reference("PAY"),
        payer=payer,
        purpose=purpose,
        object_id=str(object_id),
        description=payable.description[:200],
        amount_minor=payable.amount_minor,
        currency=payable.currency,
        platform_fee_minor=payable.platform_fee_minor,
        payee_id=payable.payee_id,
        escrow=bool(payable.escrow and payable.payee_id),
        provider=provider_obj.key,
        expires_at=expires_at,
        metadata={k: v for k, v in payable.metadata.items() if isinstance(v, str | int | bool)},
    )
    checkout = provider_obj.initialize(
        reference=intent.reference,
        amount_minor=intent.amount_minor,
        currency=intent.currency,
        email=payer.email,
        description=intent.description,
        callback_url=_callback_url(intent.reference, callback_url),
        metadata={"reference": intent.reference, "purpose": purpose, "object_id": str(object_id)},
    )
    intent.checkout_url = checkout.checkout_url[:1000]
    intent.provider_reference = checkout.provider_reference[:255]
    intent.save()
    audit("payments.checkout.started", actor=payer, target=intent, category="payments")
    return intent


def _locked(reference: str) -> PaymentIntent:
    intent = PaymentIntent.objects.select_for_update().filter(reference=reference).first()
    if intent is None:
        raise NotFound("Payment not found.")
    return intent


def verify_payment(*, reference: str, user: Any = None) -> PaymentIntent:
    """Ask the provider about a payment and apply the result (payer, staff or webhooks)."""
    intent = PaymentIntent.objects.filter(reference=reference).first()
    if intent is None:
        raise NotFound("Payment not found.")
    if user is not None and intent.payer_id != user.pk:
        authorize(user, "payments.view")
    if intent.status in PAID_STATUSES or intent.status == IntentStatus.REFUNDED:
        return intent
    txn = get_provider(intent.provider).verify(intent.reference, intent.provider_reference)
    return apply_transaction(intent.reference, txn)


@transaction.atomic
def apply_transaction(reference: str, txn: ProviderTransaction) -> PaymentIntent:
    intent = _locked(reference)
    if intent.status in PAID_STATUSES or intent.status == IntentStatus.REFUNDED:
        return intent  # Already applied: idempotent.
    if txn.status == "succeeded":
        return _succeed(intent, txn)
    if txn.status in ("failed", "abandoned") and intent.status == IntentStatus.PENDING:
        intent.status = IntentStatus.FAILED
        intent.failure_reason = txn.status
        intent.save(update_fields=["status", "failure_reason", "updated_at"])
        publish(events.PAYMENT_FAILED, _payload(intent))
    return intent


def _succeed(intent: PaymentIntent, txn: ProviderTransaction) -> PaymentIntent:
    intent.provider_transaction_id = txn.provider_transaction_id[:128]
    intent.channel = txn.channel[:32]
    intent.paid_at = txn.paid_at or timezone.now()
    mismatch = txn.amount_minor != intent.amount_minor
    intent.status = IntentStatus.SUCCEEDED
    try:
        with transaction.atomic():
            intent.save()
    except IntegrityError:
        # This provider transaction already settled another intent: don't count it twice.
        raise Conflict("This transaction was already applied.", code="duplicate_transaction") from None
    if txn.currency.upper() != intent.currency:
        # Can't book foreign money against this intent: hold for finance to review.
        logger.error("Payment %s settled in %s, expected %s", intent.reference, txn.currency, intent.currency)
        intent.failure_reason = "currency_mismatch"
        intent.save(update_fields=["failure_reason", "updated_at"])
        publish(events.PAYMENT_UNFULFILLED, _payload(intent, reason="currency_mismatch"))
        return intent
    if mismatch:
        # Money arrived, but not what was owed: book what arrived and return it in full.
        logger.warning("Payment %s amount mismatch: got %s", intent.reference, txn.amount_minor)
        intent.amount_minor = txn.amount_minor
        intent.platform_fee_minor = min(intent.platform_fee_minor, intent.amount_minor)
        intent.save(update_fields=["amount_minor", "platform_fee_minor", "updated_at"])
        ledger.record_payment(intent)
        _unfulfilled(intent, "amount_mismatch")
        return intent
    ledger.record_payment(intent)
    try:
        with transaction.atomic():
            get_payable_adapter(intent.purpose).on_paid(
                intent.object_id, reference=intent.reference, amount_minor=intent.amount_minor, currency=intent.currency
            )
    except (Conflict, NotFound) as exc:
        _unfulfilled(intent, getattr(exc, "code", "unfulfillable"))
        return intent
    audit("payments.payment.succeeded", actor=None, target=intent, category="payments")
    publish(events.PAYMENT_SUCCEEDED, _payload(intent))
    return intent


def _unfulfilled(intent: PaymentIntent, reason: str) -> None:
    intent.failure_reason = reason[:64]
    intent.save(update_fields=["failure_reason", "updated_at"])
    publish(events.PAYMENT_UNFULFILLED, _payload(intent, reason=reason))
    if intent.refundable_minor > 0:
        create_refund(intent, intent.refundable_minor, reason=f"Automatic refund: {reason}")


@transaction.atomic
def handle_notice(provider_key: str, notice: WebhookNotice) -> None:
    """Act on a verified webhook: re-verify payments, settle refunds."""
    if notice.provider_refund_id:
        refund = Refund.objects.select_for_update().filter(provider_refund_id=notice.provider_refund_id).first()
        if (
            refund is not None
            and refund.status == RefundStatus.PENDING
            and notice.refund_status in ("succeeded", "failed")
        ):
            _settle_refund(refund, notice.refund_status)
        return
    if notice.reference:
        intent = PaymentIntent.objects.filter(reference=notice.reference, provider=provider_key).first()
        if intent is None:
            return  # Not ours (or another environment's): acknowledge and ignore.
        verify_payment(reference=intent.reference)


# ------------------------------------------------------------------ refunds
def create_refund(intent: PaymentIntent, amount_minor: int, *, reason: str, actor: Any = None) -> Refund:
    """Refund part or all of a paid intent. Call inside a transaction holding the intent lock."""
    if intent.status not in PAID_STATUSES:
        raise Conflict("Only successful payments can be refunded.", code="not_refundable")
    pending = sum(r.amount_minor for r in intent.refunds.filter(status=RefundStatus.PENDING))
    if amount_minor <= 0 or amount_minor > intent.refundable_minor - pending:
        raise ValidationError(details={"amount_minor": ["More than the refundable amount."]}, code="refund_too_large")
    refund = Refund.objects.create(
        intent=intent, reference=_reference("RFD"), amount_minor=amount_minor, reason=reason[:255], requested_by=actor
    )
    transaction.on_commit(lambda: _submit_refund_task_or_now(str(refund.pk)))
    return refund


def _submit_refund_task_or_now(refund_id: str) -> None:
    from university.core.tasks import enqueue

    enqueue(submit_refund, refund_id)


@task(name="university.payments.submit_refund")
def submit_refund(refund_id: str) -> None:
    with transaction.atomic():
        refund = Refund.objects.select_for_update(of=("self",)).select_related("intent").filter(pk=refund_id).first()
        if refund is None or refund.status != RefundStatus.PENDING or refund.provider_refund_id:
            return
        intent = refund.intent
        refund.attempts += 1
        try:
            result = get_provider(intent.provider).refund(
                provider_transaction_id=intent.provider_transaction_id,
                reference=refund.reference,
                amount_minor=refund.amount_minor,
                currency=intent.currency,
            )
        except (ProviderError, ValidationError) as exc:
            refund.error = str(getattr(exc, "code", "provider_error"))[:64]
            if refund.attempts >= int(payments_settings.get("MAX_REFUND_ATTEMPTS", 5)):
                refund.status = RefundStatus.FAILED
                refund.save(update_fields=["attempts", "error", "status", "updated_at"])
                publish(events.REFUND_FAILED, {"refund_id": refund.pk, **_payload(intent)})
            else:
                refund.save(update_fields=["attempts", "error", "updated_at"])
            return
        refund.provider_refund_id = result.provider_refund_id[:128]
        refund.save(update_fields=["attempts", "provider_refund_id", "updated_at"])
        if result.status in ("succeeded", "failed"):
            _settle_refund(refund, result.status)


def _settle_refund(refund: Refund, status: str) -> None:
    intent = PaymentIntent.objects.select_for_update().get(pk=refund.intent_id)
    refund.intent = intent
    refund.completed_at = timezone.now()
    if status == "failed":
        refund.status = RefundStatus.FAILED
        refund.save(update_fields=["status", "completed_at", "updated_at"])
        publish(events.REFUND_FAILED, {"refund_id": refund.pk, **_payload(intent)})
        return
    refund.status = RefundStatus.SUCCEEDED
    refund.save(update_fields=["status", "completed_at", "updated_at"])
    intent.amount_refunded_minor += refund.amount_minor
    intent.status = IntentStatus.REFUNDED if intent.refundable_minor == 0 else IntentStatus.PARTIALLY_REFUNDED
    intent.save(update_fields=["amount_refunded_minor", "status", "updated_at"])
    ledger.record_refund(refund)
    try:
        get_payable_adapter(intent.purpose).on_refunded(
            intent.object_id, reference=intent.reference, amount_minor=refund.amount_minor, currency=intent.currency
        )
    except Exception:  # The refund happened; a module's bookkeeping must not undo it.
        logger.exception("on_refunded failed for %s", intent.reference)
    publish(
        events.REFUND_SUCCEEDED,
        {"refund_id": refund.pk, "refund_amount_minor": refund.amount_minor, **_payload(intent)},
    )


@task(name="university.payments.retry_refunds")
def retry_refunds() -> int:
    """Resubmit pending refunds that never reached the provider (run every few minutes)."""
    pending = Refund.objects.filter(status=RefundStatus.PENDING, provider_refund_id="").values_list("pk", flat=True)
    for refund_id in list(pending):
        submit_refund(str(refund_id))
    return len(pending)


@transaction.atomic
def refund_payment(*, actor: Any, reference: str, amount_minor: int | None = None, reason: str) -> Refund:
    """Staff refunds (``payments.refunds.manage``)."""
    authorize(actor, "payments.refunds.manage", audit_denial=True)
    intent = _locked(reference)
    refund = create_refund(intent, amount_minor or intent.refundable_minor, reason=reason, actor=actor)
    audit(
        "payments.refund.requested",
        actor=actor,
        target=intent,
        category="payments",
        metadata={"amount_minor": refund.amount_minor, "reason": reason[:255]},
    )
    return refund


def _paid_intent_for(purpose: str, object_id: Any) -> PaymentIntent | None:
    return (
        PaymentIntent.objects.select_for_update()
        .filter(purpose=purpose, object_id=str(object_id), status__in=PAID_STATUSES)
        .order_by("-paid_at")
        .first()
    )


@transaction.atomic
def refund_for(purpose: str, object_id: Any, *, amount_minor: int | None = None, reason: str = "") -> Refund | None:
    """Refund whatever was paid for an object (requested by its selling module)."""
    intent = _paid_intent_for(purpose, object_id)
    if intent is None or intent.refundable_minor <= 0:
        return None
    return create_refund(
        intent, amount_minor or intent.refundable_minor, reason=reason or "Requested by the seller module"
    )


@transaction.atomic
def release_for(purpose: str, object_id: Any) -> int:
    """Release escrowed funds to the payee (requested by its selling module)."""
    intent = _paid_intent_for(purpose, object_id)
    if intent is None or not intent.escrow or intent.released_at is not None:
        return 0
    released = ledger.record_release(intent)
    intent.released_at = timezone.now()
    intent.save(update_fields=["released_at", "updated_at"])
    publish(events.FUNDS_RELEASED, {**_payload(intent), "released_minor": released})
    return released


@task(name="university.payments.expire_intents")
def expire_intents() -> int:
    return PaymentIntent.objects.filter(status=IntentStatus.PENDING, expires_at__lt=timezone.now()).update(
        status=IntentStatus.EXPIRED, updated_at=timezone.now()
    )


# ------------------------------------------------------------------ payouts
_ACCOUNT_NUMBER = re.compile(r"\d{7,}")


@transaction.atomic
def request_payout(*, user: Any, amount_minor: int, currency: str, destination: str) -> Payout:
    rate_limit("payments_payout", key=str(user.pk))
    destination = (destination or "").strip()
    if not destination or _ACCOUNT_NUMBER.search(destination.replace(" ", "")):
        raise ValidationError(
            details={"destination": ["Describe the destination without full account numbers (e.g. 'GTBank ••••1234')."]}
        )
    minimum = int((payments_settings.get("MIN_PAYOUT_MINOR") or {}).get(currency, 1))
    if amount_minor < minimum:
        raise ValidationError(details={"amount_minor": [f"The minimum payout is {minimum}."]})
    # Serialise payouts per person: lock their user row.
    get_user_model().objects.select_for_update().get(pk=user.pk)
    available = ledger.balance(f"payee:{user.pk}:available", currency)
    if amount_minor > available:
        raise ValidationError("Not enough available balance.", code="insufficient_balance")
    payout = Payout.objects.create(
        payee=user, amount_minor=amount_minor, currency=currency, destination=destination[:120]
    )
    ledger.record_payout(payout, EntryKind.PAYOUT_REQUESTED)
    publish(events.PAYOUT_REQUESTED, {"payout_id": payout.pk, "payee_id": user.pk}, actor=user)
    return payout


@transaction.atomic
def decide_payout(*, actor: Any, payout_id: Any, approve: bool, external_reference: str = "", note: str = "") -> Payout:
    authorize(actor, "payments.payouts.manage", audit_denial=True)
    payout = Payout.objects.select_for_update().filter(pk=payout_id).first()
    if payout is None:
        raise NotFound("Payout not found.")
    if payout.payee_id == actor.pk:
        raise PermissionDenied("You can't process your own payout.", code="conflict_of_interest")
    if payout.status != PayoutStatus.REQUESTED:
        raise Conflict("This payout was already processed.", code="already_processed")
    if approve and not external_reference.strip():
        raise ValidationError(details={"external_reference": ["Record the transfer reference."]})
    payout.status = PayoutStatus.PAID if approve else PayoutStatus.REJECTED
    payout.processed_by = actor
    payout.processed_at = timezone.now()
    payout.external_reference = external_reference.strip()[:128]
    payout.note = note[:255]
    payout.save()
    ledger.record_payout(payout, EntryKind.PAYOUT_PAID if approve else EntryKind.PAYOUT_REVERSED)
    audit(f"payments.payout.{'paid' if approve else 'rejected'}", actor=actor, target=payout, category="payments")
    publish(
        events.PAYOUT_PAID if approve else events.PAYOUT_REJECTED,
        {"payout_id": payout.pk, "payee_id": payout.payee_id},
        actor=actor,
    )
    return payout


@transaction.atomic
def cancel_payout(*, user: Any, payout_id: Any) -> Payout:
    payout = Payout.objects.select_for_update().filter(pk=payout_id, payee=user).first()
    if payout is None:
        raise NotFound("Payout not found.")
    if payout.status != PayoutStatus.REQUESTED:
        raise Conflict("This payout was already processed.", code="already_processed")
    payout.status = PayoutStatus.CANCELLED
    payout.save(update_fields=["status", "updated_at"])
    ledger.record_payout(payout, EntryKind.PAYOUT_REVERSED)
    return payout
