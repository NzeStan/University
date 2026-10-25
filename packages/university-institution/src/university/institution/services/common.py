from __future__ import annotations

from typing import Any

from django.core.exceptions import ObjectDoesNotExist
from django.core.exceptions import ValidationError as DjangoValidationError
from django.db import IntegrityError, models, transaction

from university.core.exceptions import Conflict, ValidationError
from university.institution.constants import INSTITUTION_SCOPE
from university.permissions.scopes import Scope


def institution_scope(institution: Any) -> Scope:
    return Scope(INSTITUTION_SCOPE, getattr(institution, "pk", institution))


def save_validated(instance: models.Model, *, conflict_message: str = "This already exists.") -> models.Model:
    """``full_clean`` then save, mapping errors to University exceptions."""
    try:
        instance.full_clean(validate_unique=False, validate_constraints=False)
    except DjangoValidationError as exc:
        raise ValidationError(details=exc.message_dict) from None
    try:
        with transaction.atomic():
            instance.save()
    except IntegrityError:
        raise Conflict(conflict_message) from None
    return instance


def _current(instance: models.Model, field: str) -> Any:
    try:
        return getattr(instance, field)
    except ObjectDoesNotExist:  # unset relation on an unsaved instance
        return None


def apply_fields(instance: models.Model, data: dict[str, Any], allowed: tuple[str, ...]) -> list[str]:
    unknown = set(data) - set(allowed)
    if unknown:
        raise ValidationError(details={field: ["This field cannot be changed."] for field in sorted(unknown)})
    changed = [field for field, value in data.items() if _current(instance, field) != value]
    for field in changed:
        setattr(instance, field, data[field])
    return changed


def ensure_same_institution(institution_id: Any, **objects: Any) -> None:
    """Reject references to structure belonging to another institution (BOLA)."""
    for name, obj in objects.items():
        if obj is not None and obj.institution_id != institution_id:
            raise ValidationError(details={name: ["Does not belong to this institution."]})


def validate_choice(value: str, allowed: list[str], field: str) -> None:
    if value and value not in allowed:
        raise ValidationError(details={field: [f"Must be one of: {', '.join(allowed)}."]})
