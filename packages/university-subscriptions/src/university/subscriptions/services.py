"""Subscriptions: members pay for a period at a time and hold their plan's entitlements meanwhile.

Rules:

* One live subscription per member (pending, active or in its grace period). Changing plan means
  letting the current one end first: nobody pays twice for overlapping time.
* Periods are paid through university-payments (purpose ``subscriptions.period``). A payment
  that arrives when nothing is due (a double payment) is refused, and payments refunds it.
* Renewals are paid by the member (no stored cards): a reminder goes out before the period ends,
  and entitlements continue through a short grace period before the subscription expires.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core import entitlements as core_entitlements
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, ValidationError
from university.core.ids import is_valid_uuid
from university.subscriptions import events
from university.subscriptions.conf import plans, price
from university.subscriptions.conf import subscriptions_settings as conf
from university.subscriptions.models import ENTITLED, LIVE, Period, Subscription, SubscriptionStatus

PURPOSE = "subscriptions.period"


def _payload(sub: Subscription) -> dict[str, Any]:
    return {"subscription_id": sub.pk, "user_id": sub.user_id, "plan": sub.plan}


def current(user: Any) -> Subscription | None:
    """The member's live subscription, if any."""
    if user is None or not getattr(user, "is_authenticated", False):
        return None
    return Subscription.objects.filter(user=user, status__in=LIVE).first()


def user_entitlements(user: Any) -> list[str]:
    """Core hook: the entitlements of the member's plan while it's paid up (or in grace)."""
    sub = Subscription.objects.filter(user=user, status__in=ENTITLED).only("plan").first()
    if sub is None:
        return []
    return list(plans().get(sub.plan, {}).get("entitlements", []))


def subscribe(*, user: Any, plan: str, interval: str, currency: str) -> Subscription:
    if plan not in plans():
        raise ValidationError(details={"plan": ["Unknown plan."]})
    if price(plan, interval, currency) is None:
        raise ValidationError(details={"interval": ["This plan isn't sold for that interval and currency."]})
    with transaction.atomic():
        existing = Subscription.objects.select_for_update().filter(user=user, status__in=LIVE).first()
        if existing is not None and existing.status != SubscriptionStatus.PENDING_PAYMENT:
            raise Conflict(
                "You already have a subscription. Let it end before choosing another plan.", code="already_subscribed"
            )
        if existing is not None:
            # Not paid yet: just change what they're about to buy.
            existing.plan, existing.interval, existing.currency = plan, interval, currency
            existing.save(update_fields=["plan", "interval", "currency", "updated_at"])
            return existing
        try:
            with transaction.atomic():
                sub = Subscription.objects.create(user=user, plan=plan, interval=interval, currency=currency)
        except IntegrityError:
            raise Conflict("You already have a subscription.", code="already_subscribed") from None
    audit("subscriptions.subscription.started", actor=user, target=sub, category="payments")
    return sub


def abandon(*, user: Any) -> None:
    """Drop an unpaid subscription (e.g. the member changed their mind at checkout)."""
    updated = Subscription.objects.filter(user=user, status=SubscriptionStatus.PENDING_PAYMENT).update(
        status=SubscriptionStatus.ABANDONED
    )
    if not updated:
        raise NotFound("Nothing to cancel.")


def set_cancel_at_period_end(*, user: Any, cancel: bool) -> Subscription:
    sub = Subscription.objects.filter(user=user, status__in=ENTITLED).first()
    if sub is None:
        raise NotFound("You don't have an active subscription.")
    sub.cancel_at_period_end = cancel
    sub.save(update_fields=["cancel_at_period_end", "updated_at"])
    audit(
        "subscriptions.subscription.cancelled" if cancel else "subscriptions.subscription.resumed",
        actor=user,
        target=sub,
        category="payments",
    )
    return sub


def amount_due(sub: Subscription, *, now: dt.datetime | None = None) -> int | None:
    """What paying now costs, or None when nothing is due yet (or the plan is no longer sold)."""
    now = now or timezone.now()
    if sub.status == SubscriptionStatus.ACTIVE:
        window = dt.timedelta(days=int(conf.get("RENEWAL_WINDOW_DAYS", 7)))
        if sub.current_period_end is None or sub.current_period_end - now > window:
            return None
    elif sub.status not in (SubscriptionStatus.PENDING_PAYMENT, SubscriptionStatus.PAST_DUE):
        return None
    return price(sub.plan, sub.interval, sub.currency)


def pay_period(object_id: Any, *, reference: str, amount_minor: int, currency: str) -> Subscription:
    """A period was paid: activate or extend. Called by the payable adapter."""
    with transaction.atomic():
        sub = (
            Subscription.objects.select_for_update().filter(pk=object_id).first() if is_valid_uuid(object_id) else None
        )
        if sub is None:
            raise NotFound("No such subscription.")
        due = amount_due(sub)
        if due is None or due != amount_minor or currency != sub.currency:
            raise Conflict("Nothing is due on this subscription.", code="not_due")
        now = timezone.now()
        first = sub.status == SubscriptionStatus.PENDING_PAYMENT
        # An early renewal continues from the end of the paid time; a new or lapsed one starts now.
        restart = first or sub.status == SubscriptionStatus.PAST_DUE or sub.current_period_end is None
        start = now if restart else max(now, sub.current_period_end)
        end = start + dt.timedelta(days=int(conf.get("INTERVAL_DAYS", {}).get(sub.interval, 30)))
        Period.objects.create(
            subscription=sub,
            starts_at=start,
            ends_at=end,
            amount_minor=amount_minor,
            currency=currency,
            payment_reference=reference,
        )
        if restart:
            sub.current_period_start = start
        sub.current_period_end = end
        sub.status = SubscriptionStatus.ACTIVE
        sub.cancel_at_period_end = False
        sub.save()
    core_entitlements.forget(sub.user)
    publish(events.SUBSCRIPTION_ACTIVATED if first else events.SUBSCRIPTION_RENEWED, _payload(sub))
    audit("subscriptions.period.paid", actor=None, target=sub, category="payments", metadata={"reference": reference})
    return sub


def refund_period(reference: str) -> None:
    """A paid period was refunded: take that time back. Payments that bought nothing are no-ops."""
    with transaction.atomic():
        period = Period.objects.select_related("subscription").filter(payment_reference=reference).first()
        if period is None:
            return
        sub = Subscription.objects.select_for_update().get(pk=period.subscription_id)
        length = period.ends_at - period.starts_at
        if sub.current_period_end is not None:
            sub.current_period_end = max(period.starts_at, sub.current_period_end - length)
            sub.save(update_fields=["current_period_end", "updated_at"])
        period.delete()
    audit(
        "subscriptions.period.refunded", actor=None, target=sub, category="payments", metadata={"reference": reference}
    )
    if sub.current_period_end is None or sub.current_period_end <= timezone.now():
        _expire(sub)
    core_entitlements.forget(sub.user)


def sweep(*, now: dt.datetime | None = None) -> dict[str, int]:
    """Move subscriptions along as time passes: reminders, grace and expiry. Safe to run often."""
    now = now or timezone.now()
    counts = {"reminded": 0, "past_due": 0, "expired": 0}
    reminder_at = now + dt.timedelta(days=int(conf.get("REMINDER_DAYS", 3)))
    for sub in Subscription.objects.filter(
        status=SubscriptionStatus.ACTIVE,
        cancel_at_period_end=False,
        current_period_end__lte=reminder_at,
        current_period_end__gt=now,
    ):
        if sub.reminded_for != sub.current_period_end:
            Subscription.objects.filter(pk=sub.pk).update(reminded_for=sub.current_period_end)
            publish(events.SUBSCRIPTION_RENEWAL_DUE, _payload(sub))
            counts["reminded"] += 1
    ended = Subscription.objects.filter(status=SubscriptionStatus.ACTIVE, current_period_end__lte=now)
    for sub in ended:
        if sub.cancel_at_period_end:
            _expire(sub)
            counts["expired"] += 1
        else:
            Subscription.objects.filter(pk=sub.pk, status=SubscriptionStatus.ACTIVE).update(
                status=SubscriptionStatus.PAST_DUE
            )
            counts["past_due"] += 1
    grace = dt.timedelta(days=int(conf.get("GRACE_DAYS", 3)))
    for sub in Subscription.objects.filter(status=SubscriptionStatus.PAST_DUE, current_period_end__lte=now - grace):
        _expire(sub)
        counts["expired"] += 1
    stale = now - dt.timedelta(days=2)
    Subscription.objects.filter(status=SubscriptionStatus.PENDING_PAYMENT, created_at__lte=stale).update(
        status=SubscriptionStatus.ABANDONED
    )
    return counts


def _expire(sub: Subscription) -> None:
    updated = Subscription.objects.filter(pk=sub.pk, status__in=ENTITLED).update(status=SubscriptionStatus.EXPIRED)
    if updated:
        publish(events.SUBSCRIPTION_EXPIRED, _payload(sub))
