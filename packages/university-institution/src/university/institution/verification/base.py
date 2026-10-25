from __future__ import annotations

import datetime as dt
from collections.abc import Mapping
from typing import Any

from django.utils import timezone
from django.utils.module_loading import import_string

from university.core.exceptions import NotFound, ValidationError
from university.institution.conf import institution_settings
from university.institution.constants import VerificationStatus
from university.institution.models import InstitutionMembership, VerificationRequest


class VerificationProvider:
    """Base class for membership verification providers.

    ``start`` begins verification and returns a :class:`VerificationRequest`
    whose status is ``approved`` (instant proof), ``awaiting_user`` (the user
    must complete a step, e.g. enter a code) or ``pending_review`` (a human
    reviewer decides). ``complete`` finishes an ``awaiting_user`` request.
    Providers never change membership status themselves; the service does.
    """

    key: str = ""
    label: str = ""
    #: True when a reviewer must decide (shown in reviewer queues).
    requires_review: bool = False

    def start(
        self, *, membership: InstitutionMembership, data: Mapping[str, Any], file: Any = None
    ) -> VerificationRequest:
        raise NotImplementedError

    def complete(self, *, request: VerificationRequest, data: Mapping[str, Any]) -> VerificationRequest:
        raise ValidationError("This verification method has no completion step.", code="not_supported")

    # -- helpers ----------------------------------------------------------
    def create_request(
        self,
        membership: InstitutionMembership,
        *,
        status: str | None = None,
        approved: bool = False,
        evidence: Mapping[str, Any] | None = None,
        **fields: Any,
    ) -> VerificationRequest:
        if status is None:
            status = VerificationStatus.APPROVED if approved else VerificationStatus.PENDING_REVIEW
        ttl_days = int(institution_settings.get("VERIFICATION_REQUEST_TTL_DAYS", 30))
        fields.setdefault("expires_at", timezone.now() + dt.timedelta(days=ttl_days))
        return VerificationRequest.objects.create(
            membership=membership,
            method=self.key,
            status=status,
            evidence=dict(evidence or {}),
            decided_at=timezone.now() if status == VerificationStatus.APPROVED else None,
            **fields,
        )


_instances: dict[tuple[str, str], VerificationProvider] = {}


def list_providers() -> dict[str, str]:
    return dict(institution_settings.get("VERIFICATION_PROVIDERS", {}))


def get_provider(key: str) -> VerificationProvider:
    path = list_providers().get(key)
    if not path:
        raise NotFound("Unknown verification method.")
    cache_key = (key, path)
    if cache_key not in _instances:
        provider = import_string(path)()
        provider.key = key
        _instances[cache_key] = provider
    return _instances[cache_key]
