"""Validation and normalisation of user identifiers."""

from __future__ import annotations

import re

from django.core.exceptions import ValidationError
from django.utils.deconstruct import deconstructible
from django.utils.translation import gettext_lazy as _

from university.core.conf import university_settings

_HANDLE_RE = re.compile(r"^[a-z0-9](?:[a-z0-9_]*[a-z0-9])?$")
_E164_RE = re.compile(r"^\+[1-9]\d{6,14}$")


def normalize_email(email: str) -> str:
    """Trim and lowercase an email address.

    The whole address is lowercased: case-sensitive local parts are legal but
    in practice cause duplicate accounts and impersonation.
    """
    return (email or "").strip().lower()


def normalize_handle(handle: str | None) -> str | None:
    if handle is None:
        return None
    handle = handle.strip().lstrip("@").lower()
    return handle or None


def normalize_phone(phone: str) -> str:
    """Strip formatting characters; the result must be E.164 (``+234…``)."""
    return re.sub(r"[\s\-().]", "", phone or "")


@deconstructible
class HandleValidator:
    message = _(
        "Handles may contain lowercase letters, numbers and underscores, and must start and end "
        "with a letter or number."
    )

    def __call__(self, value: str) -> None:
        min_len = int(university_settings.get("USERS.HANDLE_MIN_LENGTH", 3))
        max_len = int(university_settings.get("USERS.HANDLE_MAX_LENGTH", 30))
        if not (min_len <= len(value) <= max_len):
            raise ValidationError(
                _("Handles must be between %(min)d and %(max)d characters."),
                code="invalid_handle_length",
                params={"min": min_len, "max": max_len},
            )
        if not _HANDLE_RE.match(value) or "__" in value:
            raise ValidationError(self.message, code="invalid_handle")
        reserved = {h.lower() for h in university_settings.get("USERS.RESERVED_HANDLES", [])}
        if value in reserved:
            raise ValidationError(_("This handle is not available."), code="reserved_handle")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, HandleValidator)


@deconstructible
class E164PhoneValidator:
    message = _("Enter a phone number in international format, e.g. +2348012345678.")

    def __call__(self, value: str) -> None:
        if not _E164_RE.match(value):
            raise ValidationError(self.message, code="invalid_phone")

    def __eq__(self, other: object) -> bool:
        return isinstance(other, E164PhoneValidator)


validate_handle = HandleValidator()
validate_phone = E164PhoneValidator()
