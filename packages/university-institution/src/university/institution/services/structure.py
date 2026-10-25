"""Academic structure: campuses, academic units, programmes, levels, sessions."""

from __future__ import annotations

from typing import Any

from django.db import models, transaction
from django.utils.text import slugify

from university.audit.services import record as audit
from university.core.exceptions import ValidationError
from university.institution.conf import institution_settings
from university.institution.models import (
    AcademicSession,
    AcademicUnit,
    Campus,
    Institution,
    Level,
    Programme,
    Semester,
)
from university.institution.services.common import (
    apply_fields,
    ensure_same_institution,
    institution_scope,
    save_validated,
    validate_choice,
)
from university.permissions.services import authorize

PERMISSION = "institution.structure.manage"

#: Fields editable per model (relations are validated separately).
UPDATABLE = {
    Campus: ("name", "address", "city", "region", "is_main", "is_active"),
    AcademicUnit: ("name", "short_name", "code", "unit_type", "parent", "campus", "is_active"),
    Programme: (
        "name",
        "code",
        "award",
        "qualification_level",
        "study_mode",
        "duration_years",
        "academic_unit",
        "is_active",
    ),
    Level: ("code", "name", "order", "programme"),
    AcademicSession: ("name", "starts_on", "ends_on"),
    Semester: ("name", "order", "starts_on", "ends_on"),
}


def _audit(action: str, actor: Any, obj: models.Model, institution_id: Any, **metadata: Any) -> None:
    audit(action, actor=actor, target=obj, scope=("institution", institution_id), metadata=metadata)


def _slug(data: dict[str, Any]) -> str:
    return (data.pop("slug", None) or slugify(data.get("short_name") or data.get("name", "")))[:100]


def _check_unit_parent(unit: AcademicUnit, parent: AcademicUnit | None) -> None:
    if parent is None:
        return
    ensure_same_institution(unit.institution_id, parent=parent)
    node: AcademicUnit | None = parent
    depth = 0
    while node is not None and depth < 32:
        if unit.pk is not None and node.pk == unit.pk:
            raise ValidationError(details={"parent": ["A unit cannot be placed under itself."]})
        node = node.parent
        depth += 1


@transaction.atomic
def create_campus(*, actor: Any, institution: Institution, data: dict[str, Any]) -> Campus:
    authorize(actor, PERMISSION, institution_scope(institution), audit_denial=True)
    data = dict(data)
    campus = Campus(institution=institution, slug=_slug(data))
    apply_fields(campus, data, UPDATABLE[Campus])
    if campus.is_main:
        Campus.objects.filter(institution=institution, is_main=True).update(is_main=False)
    save_validated(campus, conflict_message="A campus with this slug already exists.")
    _audit("institution.campus.created", actor, campus, institution.pk)
    return campus


@transaction.atomic
def create_academic_unit(*, actor: Any, institution: Institution, data: dict[str, Any]) -> AcademicUnit:
    authorize(actor, PERMISSION, institution_scope(institution), audit_denial=True)
    data = dict(data)
    validate_choice(data.get("unit_type", ""), institution_settings.get("ACADEMIC_UNIT_TYPES"), "unit_type")
    if not data.get("unit_type"):
        raise ValidationError(details={"unit_type": ["This field is required."]})
    unit = AcademicUnit(institution=institution, slug=_slug(data))
    apply_fields(unit, data, UPDATABLE[AcademicUnit])
    _check_unit_parent(unit, unit.parent)
    ensure_same_institution(institution.pk, campus=unit.campus)
    save_validated(unit, conflict_message="A unit with this slug already exists.")
    _audit("institution.unit.created", actor, unit, institution.pk, unit_type=unit.unit_type)
    return unit


@transaction.atomic
def create_programme(*, actor: Any, institution: Institution, data: dict[str, Any]) -> Programme:
    authorize(actor, PERMISSION, institution_scope(institution), audit_denial=True)
    data = dict(data)
    validate_choice(
        data.get("qualification_level", ""), institution_settings.get("QUALIFICATION_LEVELS"), "qualification_level"
    )
    validate_choice(data.get("study_mode", ""), institution_settings.get("STUDY_MODES"), "study_mode")
    programme = Programme(institution=institution)
    apply_fields(programme, data, UPDATABLE[Programme])
    ensure_same_institution(institution.pk, academic_unit=programme.academic_unit)
    save_validated(programme, conflict_message="A programme with this code already exists.")
    _audit("institution.programme.created", actor, programme, institution.pk)
    return programme


@transaction.atomic
def create_level(*, actor: Any, institution: Institution, data: dict[str, Any]) -> Level:
    authorize(actor, PERMISSION, institution_scope(institution), audit_denial=True)
    level = Level(institution=institution)
    apply_fields(level, dict(data), UPDATABLE[Level])
    ensure_same_institution(institution.pk, programme=level.programme)
    save_validated(level, conflict_message="A level with this code already exists.")
    _audit("institution.level.created", actor, level, institution.pk)
    return level


@transaction.atomic
def create_session(
    *, actor: Any, institution: Institution, data: dict[str, Any], make_current: bool = False
) -> AcademicSession:
    authorize(actor, PERMISSION, institution_scope(institution), audit_denial=True)
    session = AcademicSession(institution=institution)
    apply_fields(session, dict(data), UPDATABLE[AcademicSession])
    if session.starts_on and session.ends_on and session.ends_on <= session.starts_on:
        raise ValidationError(details={"ends_on": ["Must be after the start date."]})
    save_validated(session, conflict_message="A session with this name already exists.")
    if make_current:
        set_current_session(actor=actor, session=session)
    _audit("institution.session.created", actor, session, institution.pk)
    return session


@transaction.atomic
def set_current_session(*, actor: Any, session: AcademicSession) -> AcademicSession:
    authorize(actor, PERMISSION, institution_scope(session.institution_id), audit_denial=True)
    AcademicSession.objects.filter(institution_id=session.institution_id, is_current=True).exclude(
        pk=session.pk
    ).update(is_current=False)
    AcademicSession.objects.filter(pk=session.pk).update(is_current=True)
    session.is_current = True
    _audit("institution.session.made_current", actor, session, session.institution_id)
    return session


@transaction.atomic
def create_semester(*, actor: Any, session: AcademicSession, data: dict[str, Any]) -> Semester:
    authorize(actor, PERMISSION, institution_scope(session.institution_id), audit_denial=True)
    semester = Semester(session=session)
    apply_fields(semester, dict(data), UPDATABLE[Semester])
    if semester.starts_on and semester.ends_on and semester.ends_on <= semester.starts_on:
        raise ValidationError(details={"ends_on": ["Must be after the start date."]})
    save_validated(semester, conflict_message="A semester with this order already exists.")
    _audit("institution.semester.created", actor, semester, session.institution_id)
    return semester


@transaction.atomic
def update_structure(*, actor: Any, instance: models.Model, data: dict[str, Any]) -> models.Model:
    """Update a campus, unit, programme, level, session or semester."""
    institution_id = instance.session.institution_id if isinstance(instance, Semester) else instance.institution_id
    authorize(actor, PERMISSION, institution_scope(institution_id), audit_denial=True)
    data = dict(data)
    if isinstance(instance, AcademicUnit) and "unit_type" in data:
        validate_choice(data["unit_type"], institution_settings.get("ACADEMIC_UNIT_TYPES"), "unit_type")
    changed = apply_fields(instance, data, UPDATABLE[type(instance)])
    if isinstance(instance, AcademicUnit):
        _check_unit_parent(instance, instance.parent)
        ensure_same_institution(institution_id, campus=instance.campus)
    elif isinstance(instance, Programme):
        ensure_same_institution(institution_id, academic_unit=instance.academic_unit)
    elif isinstance(instance, Level):
        ensure_same_institution(institution_id, programme=instance.programme)
    elif isinstance(instance, Campus) and instance.is_main and "is_main" in changed:
        Campus.objects.filter(institution_id=institution_id, is_main=True).exclude(pk=instance.pk).update(is_main=False)
    if changed:
        save_validated(instance)
        _audit(f"institution.{instance._meta.model_name}.updated", actor, instance, institution_id, fields=changed)
    return instance
