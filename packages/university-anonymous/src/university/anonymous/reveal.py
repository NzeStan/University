"""Identity reveal — the only path from anonymous content to its author.

Two-person rule (``REVEAL_REQUIRES_APPROVAL``):

1. A holder of ``anonymous.identity.reveal`` files a request with a written
   justification (and optionally a case reference).
2. A *different* holder of ``anonymous.identity.reveal_approve`` approves or
   denies it. Approval expires after ``REVEAL_APPROVAL_TTL_HOURS``.
3. The requester retrieves the identity while the approval is valid.

Every step — and every retrieval — is written to the audit log. The audit
entries reference the request and the content item, never the identity, so
the audit log itself does not become an index of authors.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.contrib.auth import get_user_model
from django.db import transaction
from django.db.models import F
from django.utils import timezone

from university.anonymous.conf import anonymous_settings
from university.anonymous.identity import open_identity
from university.anonymous.models import Authorship, RevealRequest
from university.audit.services import record as audit
from university.core.exceptions import Conflict, NotFound, PermissionDenied, ValidationError
from university.core.ids import is_valid_uuid
from university.core.ratelimit import rate_limit
from university.permissions.services import authorize

REVEAL = "anonymous.identity.reveal"
APPROVE = "anonymous.identity.reveal_approve"


def _audit(action: str, actor: Any, request: RevealRequest, **metadata: Any) -> None:
    audit(
        action,
        actor=actor,
        target=request,
        category="security",
        metadata={"kind": request.kind, "object_id": str(request.object_id), **metadata},
    )


def _ttl() -> dt.datetime:
    return timezone.now() + dt.timedelta(hours=int(anonymous_settings.get("REVEAL_APPROVAL_TTL_HOURS", 24)))


@transaction.atomic
def request_reveal(
    *, requester: Any, kind: str, object_id: Any, justification: str, case_reference: str = ""
) -> RevealRequest:
    authorize(requester, REVEAL, audit_denial=True)
    rate_limit("anonymous_reveal", key=str(requester.pk))
    justification = (justification or "").strip()
    minimum = int(anonymous_settings.get("REVEAL_MIN_JUSTIFICATION", 30))
    if len(justification) < minimum:
        raise ValidationError(
            details={"justification": [f"Explain the legal or safety basis (at least {minimum} characters)."]}
        )
    if kind not in Authorship.Kind.values or not is_valid_uuid(object_id):
        raise ValidationError(details={"kind": ["Unknown content."]})
    if not Authorship.objects.filter(kind=kind, object_id=object_id).exists():
        raise NotFound("Content not found.")
    auto = not anonymous_settings.get("REVEAL_REQUIRES_APPROVAL", True)
    request = RevealRequest.objects.create(
        requester=requester,
        kind=kind,
        object_id=object_id,
        justification=justification[:4000],
        case_reference=case_reference[:128],
        status=RevealRequest.Status.APPROVED if auto else RevealRequest.Status.PENDING,
        decided_at=timezone.now() if auto else None,
        expires_at=_ttl() if auto else None,
    )
    _audit("anonymous.identity.reveal_requested", requester, request, case_reference=case_reference[:128])
    return request


@transaction.atomic
def decide_reveal(*, approver: Any, request_id: Any, approve: bool, reason: str) -> RevealRequest:
    authorize(approver, APPROVE, audit_denial=True)
    request = RevealRequest.objects.select_for_update().filter(pk=request_id).first()
    if request is None:
        raise NotFound("Request not found.")
    if request.requester_id == approver.pk:
        raise PermissionDenied("A different person must approve this request.", code="two_person_rule")
    if request.status != RevealRequest.Status.PENDING:
        raise Conflict("This request was already decided.", code="already_decided")
    request.status = RevealRequest.Status.APPROVED if approve else RevealRequest.Status.DENIED
    request.approver = approver
    request.decision_reason = (reason or "").strip()[:500]
    request.decided_at = timezone.now()
    request.expires_at = _ttl() if approve else None
    request.save(update_fields=["status", "approver", "decision_reason", "decided_at", "expires_at"])
    _audit(f"anonymous.identity.reveal_{request.status}", approver, request, reason=request.decision_reason)
    return request


@transaction.atomic
def retrieve_identity(*, requester: Any, request_id: Any) -> dict[str, Any]:
    authorize(requester, REVEAL, audit_denial=True)
    request = RevealRequest.objects.select_for_update().filter(pk=request_id, requester=requester).first()
    if request is None:
        raise NotFound("Request not found.")
    if request.status != RevealRequest.Status.APPROVED:
        raise PermissionDenied("This request has not been approved.", code="not_approved")
    if request.expires_at is None or request.expires_at <= timezone.now():
        raise PermissionDenied("This approval has expired.", code="approval_expired")
    record = Authorship.objects.filter(kind=request.kind, object_id=request.object_id).first()
    user_id = open_identity(record.identity_cipher) if record else None
    user = get_user_model().all_objects.filter(pk=user_id).first() if user_id else None
    if user is None:
        raise NotFound("The author's account no longer exists.")
    RevealRequest.objects.filter(pk=request.pk).update(retrieval_count=F("retrieval_count") + 1)
    _audit("anonymous.identity.revealed", requester, request)
    return {
        "user_id": str(user.pk),
        "email": user.email,
        "handle": user.handle,
        "display_name": user.display_name,
        "status": user.status,
    }
