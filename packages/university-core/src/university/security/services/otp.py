"""One-time codes (OTP) over email or SMS.

Guarantees:

* codes are random, short-lived (``OTP.TTL_SECONDS``) and stored as keyed
  hashes bound to their challenge id;
* each challenge allows ``OTP.MAX_ATTEMPTS`` guesses, counted atomically;
* a code is consumed atomically and can never be reused;
* issuing a new code supersedes earlier codes for the same destination;
* issuance is rate limited per destination (cooldown and hourly cap).

Delivery goes through the configured email/SMS providers via the task backend.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from django.db import transaction
from django.db.models import F
from django.utils import timezone

from university.audit.actions import AuditAction
from university.audit.services import record as audit
from university.core.conf import university_settings
from university.core.crypto import (
    generate_numeric_code,
    keyed_hash,
    mask_email,
    mask_phone,
    verify_keyed_hash,
)
from university.core.exceptions import RateLimited, ValidationError
from university.core.ids import is_valid_uuid
from university.core.providers.email import send_templated_email
from university.core.ratelimit import rate_limit
from university.core.tasks import enqueue, task
from university.security.models import OTPChallenge

_INVALID = "The code is invalid or has expired."


def _cfg() -> dict[str, Any]:
    return university_settings.get("OTP")


def destination_hash(purpose: str, destination: str) -> str:
    return keyed_hash(f"{purpose}:{destination.strip().lower()}", purpose="otp-destination")


def _code_hash(challenge_id: Any, code: str) -> str:
    return keyed_hash(f"{challenge_id}:{code}", purpose="otp-code")


@task(name="university.security.send_sms")
def send_sms_task(to: str, body: str) -> None:
    from university.core.providers import get_sms_provider

    get_sms_provider().send(to, body)


def _deliver(channel: str, destination: str, code: str, purpose: str) -> None:
    minutes = max(1, int(_cfg()["TTL_SECONDS"]) // 60)
    if channel == OTPChallenge.Channel.SMS:
        enqueue(send_sms_task, destination, f"Your verification code is {code}. It expires in {minutes} minutes.")
    else:
        send_templated_email(
            "university/security/email/otp_code",
            {"code": code, "minutes": minutes, "purpose": purpose},
            [destination],
        )


def issue_otp(*, purpose: str, channel: str, destination: str, user: Any = None) -> OTPChallenge:
    cfg = _cfg()
    if channel not in OTPChallenge.Channel.values:
        raise ValidationError(details={"channel": ["Unsupported channel."]})
    dest_hash = destination_hash(purpose, destination)
    now = timezone.now()
    cooldown = int(cfg["RESEND_COOLDOWN_SECONDS"])
    recent = (
        OTPChallenge.objects.filter(
            purpose=purpose, destination_hash=dest_hash, created_at__gt=now - dt.timedelta(seconds=cooldown)
        )
        .order_by("-created_at")
        .first()
    )
    if recent is not None:
        retry = cooldown - int((now - recent.created_at).total_seconds())
        raise RateLimited("Please wait before requesting another code.", retry_after=max(1, retry))
    rate_limit(
        "otp_issue_destination",
        key=dest_hash,
        rate=f"{int(cfg['MAX_ISSUES_PER_DESTINATION_PER_HOUR'])}/hour",
    )
    code = generate_numeric_code(int(cfg["LENGTH"]))
    challenge_id = uuid.uuid4()
    masked = mask_phone(destination) if channel == OTPChallenge.Channel.SMS else mask_email(destination)
    with transaction.atomic():
        OTPChallenge.objects.filter(
            purpose=purpose, destination_hash=dest_hash, consumed_at__isnull=True, expires_at__gt=now
        ).update(expires_at=now)
        challenge = OTPChallenge.objects.create(
            id=challenge_id,
            user=user,
            purpose=purpose,
            channel=channel,
            destination_hash=dest_hash,
            destination_masked=masked,
            code_hash=_code_hash(challenge_id, code),
            expires_at=now + dt.timedelta(seconds=int(cfg["TTL_SECONDS"])),
            max_attempts=int(cfg["MAX_ATTEMPTS"]),
        )
        _deliver(channel, destination, code, purpose)
    return challenge


def verify_otp(
    *,
    challenge_id: Any,
    code: str,
    purpose: str,
    user: Any = None,
    destination: str | None = None,
) -> OTPChallenge:
    """Verify and consume a code. Raises ``ValidationError`` on any failure."""
    invalid = ValidationError(_INVALID, code="invalid_code")
    if not is_valid_uuid(challenge_id) or not code or len(code) > 12:
        raise invalid
    challenge = OTPChallenge.objects.filter(pk=challenge_id, purpose=purpose).first()
    now = timezone.now()
    if challenge is None or challenge.consumed_at is not None or challenge.expires_at <= now:
        raise invalid
    if user is not None and challenge.user_id != user.pk:
        raise invalid
    if destination is not None and challenge.destination_hash != destination_hash(purpose, destination):
        raise invalid
    # Count the attempt atomically before comparing (no unlimited guessing).
    counted = OTPChallenge.objects.filter(
        pk=challenge.pk, attempts__lt=F("max_attempts"), consumed_at__isnull=True
    ).update(attempts=F("attempts") + 1)
    if not counted:
        audit(AuditAction.OTP_LOCKED, actor=user, target=challenge, outcome="denied")
        raise ValidationError("Too many attempts. Request a new code.", code="too_many_attempts")
    if not verify_keyed_hash(f"{challenge.pk}:{code.strip()}", challenge.code_hash, purpose="otp-code"):
        raise invalid
    consumed = OTPChallenge.objects.filter(pk=challenge.pk, consumed_at__isnull=True).update(consumed_at=now)
    if not consumed:
        raise invalid
    challenge.consumed_at = now
    return challenge
