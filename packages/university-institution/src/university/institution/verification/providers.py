"""Built-in verification providers."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, transaction

from university.core.crypto import keyed_hash, mask_email
from university.core.exceptions import ValidationError
from university.core.uploads import FileUploadValidator
from university.institution.conf import institution_settings
from university.institution.constants import VerificationStatus
from university.institution.models import InstitutionDomain, InstitutionMembership, VerificationRequest
from university.institution.verification.base import VerificationProvider
from university.security.services.otp import issue_otp, verify_otp

EMAIL_OTP_PURPOSE = "institution_email"


def identifier_hash(institution_id: Any, identifier: str) -> str:
    """Keyed hash of a student/staff number, scoped to one institution."""
    normalized = "".join(identifier.split()).upper()
    return keyed_hash(f"{institution_id}:{normalized}", purpose="institution-identifier")


def identifier_hint(identifier: str) -> str:
    compact = "".join(identifier.split())
    return ("*" * max(0, min(len(compact) - 3, 8))) + compact[-3:]


class InstitutionEmailProvider(VerificationProvider):
    """Proof by receiving a one-time code at an institutional email address."""

    label = "Institution email address"

    def start(
        self, *, membership: InstitutionMembership, data: Mapping[str, Any], file: Any = None
    ) -> VerificationRequest:
        email = str(data.get("email") or "").strip().lower()
        local, _, domain = email.partition("@")
        if not local or not domain:
            raise ValidationError(details={"email": ["Enter your institution email address."]})
        domains = InstitutionDomain.objects.filter(institution_id=membership.institution_id, is_verified=True)
        if not any(d.matches(domain) for d in domains):
            raise ValidationError(
                details={"email": ["This email domain is not registered for this institution."]},
                code="domain_not_allowed",
            )
        email_hash = keyed_hash(email, purpose="institution-email")
        already_used = VerificationRequest.objects.filter(
            method=self.key, email_hash=email_hash, status=VerificationStatus.APPROVED
        ).exists()
        if already_used:
            raise ValidationError("Unable to verify with this email address.", code="email_unavailable")
        challenge = issue_otp(purpose=EMAIL_OTP_PURPOSE, channel="email", destination=email, user=membership.user)
        return self.create_request(
            membership,
            status=VerificationStatus.AWAITING_USER,
            evidence={"email": mask_email(email)},
            email_hash=email_hash,
            otp_challenge_id=challenge.pk,
            expires_at=challenge.expires_at,
        )

    def complete(self, *, request: VerificationRequest, data: Mapping[str, Any]) -> VerificationRequest:
        verify_otp(
            challenge_id=request.otp_challenge_id,
            code=str(data.get("code") or ""),
            purpose=EMAIL_OTP_PURPOSE,
            user=request.membership.user,
        )
        request.status = VerificationStatus.APPROVED
        return request


class ManualReviewProvider(VerificationProvider):
    """A reviewer decides, optionally guided by a short note from the user."""

    label = "Manual review"
    requires_review = True

    def start(
        self, *, membership: InstitutionMembership, data: Mapping[str, Any], file: Any = None
    ) -> VerificationRequest:
        note = str(data.get("note") or "")[:500]
        return self.create_request(membership, evidence={"note": note} if note else {})


class IdentifierReviewProvider(VerificationProvider):
    """A student/staff number is checked by a reviewer.

    Only a keyed hash and a masked hint are stored; the hash also guarantees
    that one identifier can back only one open membership per role.
    """

    label = "Student / staff number"
    requires_review = True

    def start(
        self, *, membership: InstitutionMembership, data: Mapping[str, Any], file: Any = None
    ) -> VerificationRequest:
        identifier = str(data.get("identifier") or "").strip()
        if not 3 <= len(identifier) <= 64:
            raise ValidationError(details={"identifier": ["Enter your student or staff number."]})
        membership.identifier_hash = identifier_hash(membership.institution_id, identifier)
        membership.identifier_hint = identifier_hint(identifier)
        try:
            with transaction.atomic():
                membership.save(update_fields=["identifier_hash", "identifier_hint", "updated_at"])
        except IntegrityError:
            raise ValidationError("Unable to verify with this identifier.", code="identifier_unavailable") from None
        return self.create_request(membership, evidence={"identifier": membership.identifier_hint})


class DocumentReviewProvider(VerificationProvider):
    """A reviewer inspects an uploaded document (ID card, admission letter)."""

    label = "Document upload"
    requires_review = True

    def start(
        self, *, membership: InstitutionMembership, data: Mapping[str, Any], file: Any = None
    ) -> VerificationRequest:
        if file is None:
            raise ValidationError(details={"document": ["Upload a document."]})
        validator = FileUploadValidator(
            allowed_mime_types=institution_settings.get("DOCUMENT_MIME_TYPES"),
            max_bytes=institution_settings.get("DOCUMENT_MAX_BYTES"),
        )
        try:
            mime = validator(file)
        except DjangoValidationError as exc:
            raise ValidationError(details={"document": exc.messages}) from None
        request = self.create_request(membership, evidence={"document_type": mime})
        request._upload_file = file  # lets uuid_upload_to derive the extension from content
        request.document.save(file.name, file, save=True)
        return request


class AutoApproveProvider(VerificationProvider):
    """Approves immediately. For development and testing only."""

    label = "Automatic (development only)"

    def start(
        self, *, membership: InstitutionMembership, data: Mapping[str, Any], file: Any = None
    ) -> VerificationRequest:
        return self.create_request(membership, approved=True)
