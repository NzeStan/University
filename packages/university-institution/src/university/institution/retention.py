from __future__ import annotations

import datetime as dt

from django.utils import timezone

from university.institution.conf import institution_settings
from university.institution.constants import OPEN_VERIFICATION_STATUSES
from university.institution.models import VerificationRequest


def document_cutoff() -> dt.datetime | None:
    days = institution_settings.get("VERIFICATION_DOCUMENT_RETENTION_DAYS", 90)
    return None if days is None else timezone.now() - dt.timedelta(days=int(days))


def purge_verification_documents(cutoff: dt.datetime, dry_run: bool) -> int:
    """Delete stored documents of decided requests (the decision record stays)."""
    qs = (
        VerificationRequest.objects.exclude(document="")
        .exclude(status__in=OPEN_VERIFICATION_STATUSES)
        .filter(decided_at__lt=cutoff)
    )
    if dry_run:
        return qs.count()
    count = 0
    for request in qs.iterator(chunk_size=200):
        request.document.delete(save=False)
        VerificationRequest.objects.filter(pk=request.pk).update(document="")
        count += 1
    return count
