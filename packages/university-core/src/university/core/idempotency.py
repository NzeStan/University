"""Idempotency keys for unsafe API operations.

Clients send ``Idempotency-Key: <unique value>`` with requests that must not
run twice (payments, orders, registrations, external calls). The first
request executes and its response is stored; retries with the same key and
the same payload receive the stored response (``Idempotent-Replayed: true``).

* Reusing a key with a *different* payload is rejected (422).
* A retry while the first request is still running is rejected (409).
* Server errors (5xx) and exceptions are not stored, so the client can retry.
* Keys are scoped per authenticated user and per operation, so one user can
  never receive another user's stored response. Anonymous requests ignore
  the header.

Usage on a DRF view method::

    class OrderViewSet(viewsets.ViewSet):
        @idempotent("marketplace.order.create", required=True)
        def create(self, request): ...
"""

from __future__ import annotations

import datetime as dt
import functools
import hashlib
import json
from collections.abc import Callable
from typing import Any

from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.renderers import JSONRenderer
from rest_framework.response import Response

from university.core.conf import university_settings
from university.core.exceptions import Conflict, UniversityError, ValidationError
from university.core.models import IdempotencyRecord

MAX_KEY_LENGTH = 255


class IdempotencyKeyReused(UniversityError):
    status_code = 422
    default_code = "idempotency_key_reused"
    default_message = "This idempotency key was already used with a different request."


def _fingerprint(request: Any) -> str:
    try:
        body = json.dumps(request.data, sort_keys=True, default=str)
    except Exception:
        body = repr(request.data)
    raw = f"{request.method}\n{request.path}\n{body}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _replay(record: IdempotencyRecord) -> Response:
    response = Response(record.response_body, status=record.response_status)
    response["Idempotent-Replayed"] = "true"
    return response


def _begin(user: Any, scope: str, key: str, fingerprint: str) -> tuple[IdempotencyRecord, bool]:
    lock_seconds = int(university_settings.get("IDEMPOTENCY.LOCK_SECONDS", 30))
    lock_until = timezone.now() + dt.timedelta(seconds=lock_seconds)
    try:
        with transaction.atomic():
            record = IdempotencyRecord.objects.create(
                user=user, scope=scope, key=key, fingerprint=fingerprint, locked_until=lock_until
            )
        return record, True
    except IntegrityError:
        record = IdempotencyRecord.objects.get(user=user, scope=scope, key=key)
    if record.fingerprint != fingerprint:
        raise IdempotencyKeyReused()
    if record.status == IdempotencyRecord.Status.COMPLETED:
        return record, False
    # In progress: take over only if the previous holder's lock expired.
    taken = IdempotencyRecord.objects.filter(
        pk=record.pk,
        status=IdempotencyRecord.Status.IN_PROGRESS,
        locked_until__lt=timezone.now(),
    ).update(locked_until=lock_until)
    if not taken:
        raise Conflict("A request with this idempotency key is in progress.", code="idempotency_in_progress")
    record.refresh_from_db()
    return record, True


def idempotent(scope: str, *, required: bool = False) -> Callable[[Callable[..., Any]], Callable[..., Any]]:
    """Make a DRF view method idempotent under ``scope``."""

    def decorator(view_method: Callable[..., Any]) -> Callable[..., Any]:
        @functools.wraps(view_method)
        def wrapper(self: Any, request: Any, *args: Any, **kwargs: Any) -> Any:
            header = university_settings.get("IDEMPOTENCY.HEADER", "Idempotency-Key")
            key = (request.headers.get(header) or "").strip()
            user = getattr(request, "user", None)
            authenticated = bool(user and user.is_authenticated)
            if not key:
                if required and authenticated:
                    raise ValidationError(f"The {header} header is required.", code="idempotency_key_required")
                return view_method(self, request, *args, **kwargs)
            if not authenticated:
                return view_method(self, request, *args, **kwargs)
            if len(key) > MAX_KEY_LENGTH or not key.isprintable():
                raise ValidationError(f"Invalid {header} header.", code="invalid_idempotency_key")

            record, should_execute = _begin(user, scope, key, _fingerprint(request))
            if not should_execute:
                return _replay(record)
            try:
                response = view_method(self, request, *args, **kwargs)
            except Exception:
                record.delete()
                raise
            if response.status_code >= 500:
                record.delete()
                return response
            body = json.loads(JSONRenderer().render(getattr(response, "data", None)) or b"null")
            IdempotencyRecord.objects.filter(pk=record.pk).update(
                status=IdempotencyRecord.Status.COMPLETED,
                response_status=response.status_code,
                response_body=body,
                locked_until=None,
            )
            return response

        return wrapper

    return decorator
