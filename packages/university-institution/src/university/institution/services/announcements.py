"""Official institution announcements.

Only holders of ``institution.announcements.publish`` for an institution (its communications team
and administrators) can create or publish them. Publishing notifies the targeted verified members,
one notice per member, so notifications never need to import this module.
"""

from __future__ import annotations

from typing import Any

from django.db import transaction
from django.utils import timezone

from university.audit.services import record as audit
from university.core.events import publish
from university.core.exceptions import Conflict, NotFound, ValidationError
from university.core.tasks import enqueue, task
from university.institution import events
from university.institution.constants import (
    ANNOUNCEMENT_CATEGORIES,
    INSTITUTION_SCOPE,
    AnnouncementAudience,
    AnnouncementStatus,
    MembershipStatus,
)
from university.institution.models import Announcement, Institution, InstitutionMembership
from university.institution.services.common import ensure_same_institution, institution_scope
from university.permissions.services import authorize

PUBLISH = "institution.announcements.publish"
EDITABLE = ("title", "body", "category", "audience", "campus", "academic_unit", "priority", "pinned", "expires_at")


def _authorize(actor: Any, institution: Institution) -> None:
    authorize(actor, PUBLISH, scope=institution_scope(institution))


def _clean(institution: Institution, data: dict[str, Any]) -> dict[str, Any]:
    if "category" in data and data["category"] not in ANNOUNCEMENT_CATEGORIES:
        raise ValidationError(details={"category": [f"Choose one of: {', '.join(ANNOUNCEMENT_CATEGORIES)}."]})
    ensure_same_institution(institution.pk, campus=data.get("campus"), academic_unit=data.get("academic_unit"))
    expires = data.get("expires_at")
    if expires is not None and expires <= timezone.now():
        raise ValidationError(details={"expires_at": ["Choose a time in the future."]})
    return data


def _payload(announcement: Announcement) -> dict[str, Any]:
    return {
        "announcement_id": announcement.pk,
        "institution_id": announcement.institution_id,
        "priority": announcement.priority,
    }


def _audit(action: str, actor: Any, announcement: Announcement) -> None:
    audit(
        action,
        actor=actor,
        target=announcement,
        scope=(INSTITUTION_SCOPE, announcement.institution_id),
        metadata={"title": announcement.title[:100], "priority": announcement.priority},
    )


@transaction.atomic
def create_announcement(
    *, actor: Any, institution: Institution, data: dict[str, Any], publish_now: bool = False
) -> Announcement:
    _authorize(actor, institution)
    data = _clean(institution, {k: v for k, v in data.items() if k in EDITABLE})
    announcement = Announcement.objects.create(institution=institution, created_by=actor, **data)
    _audit("institution.announcement.created", actor, announcement)
    if publish_now:
        return publish_announcement(actor=actor, announcement=announcement)
    return announcement


@transaction.atomic
def update_announcement(*, actor: Any, announcement: Announcement, data: dict[str, Any]) -> Announcement:
    _authorize(actor, announcement.institution)
    if announcement.status == AnnouncementStatus.ARCHIVED:
        raise Conflict("Archived announcements can't be edited.", code="archived")
    data = _clean(announcement.institution, {k: v for k, v in data.items() if k in EDITABLE})
    for field, value in data.items():
        setattr(announcement, field, value)
    announcement.save()
    _audit("institution.announcement.updated", actor, announcement)
    if announcement.status == AnnouncementStatus.PUBLISHED:
        publish(events.ANNOUNCEMENT_UPDATED, _payload(announcement))
    return announcement


@transaction.atomic
def publish_announcement(*, actor: Any, announcement: Announcement) -> Announcement:
    _authorize(actor, announcement.institution)
    if announcement.status != AnnouncementStatus.DRAFT:
        raise Conflict("Only drafts can be published.", code="not_draft")
    announcement.status = AnnouncementStatus.PUBLISHED
    announcement.published_at = timezone.now()
    announcement.published_by = actor
    announcement.save(update_fields=["status", "published_at", "published_by", "updated_at"])
    _audit("institution.announcement.published", actor, announcement)
    publish(events.ANNOUNCEMENT_PUBLISHED, _payload(announcement))
    transaction.on_commit(lambda: enqueue(fan_out_announcement, str(announcement.pk)))
    return announcement


@transaction.atomic
def archive_announcement(*, actor: Any, announcement: Announcement) -> Announcement:
    _authorize(actor, announcement.institution)
    announcement.status = AnnouncementStatus.ARCHIVED
    announcement.pinned = False
    announcement.save(update_fields=["status", "pinned", "updated_at"])
    _audit("institution.announcement.archived", actor, announcement)
    publish(events.ANNOUNCEMENT_ARCHIVED, _payload(announcement))
    return announcement


@transaction.atomic
def delete_announcement(*, actor: Any, announcement: Announcement) -> None:
    _authorize(actor, announcement.institution)
    if announcement.status != AnnouncementStatus.DRAFT:
        raise Conflict("Published announcements are archived, not deleted.", code="archive_instead")
    _audit("institution.announcement.deleted", actor, announcement)
    announcement.delete()


def targeted_members(announcement: Announcement) -> Any:
    qs = InstitutionMembership.objects.filter(
        institution_id=announcement.institution_id, status=MembershipStatus.VERIFIED, user__status="active"
    )
    if announcement.campus_id:
        qs = qs.filter(campus_id=announcement.campus_id)
    if announcement.academic_unit_id:
        qs = qs.filter(academic_unit_id=announcement.academic_unit_id)
    return qs.values_list("user_id", flat=True).distinct()


@task(name="university.institution.fan_out_announcement")
def fan_out_announcement(announcement_id: str) -> int:
    announcement = Announcement.objects.filter(pk=announcement_id, status=AnnouncementStatus.PUBLISHED).first()
    if announcement is None:
        return 0
    count = 0
    for user_id in targeted_members(announcement).iterator(chunk_size=500):
        publish(events.ANNOUNCEMENT_NOTICE, {**_payload(announcement), "user_id": user_id})
        count += 1
    return count


def get_for_manager(*, actor: Any, institution: Institution, announcement_id: Any) -> Announcement:
    announcement = Announcement.objects.filter(pk=announcement_id, institution=institution).first()
    if announcement is None:
        raise NotFound()
    _authorize(actor, institution)
    return announcement


__all__ = [
    "AnnouncementAudience",
    "archive_announcement",
    "create_announcement",
    "delete_announcement",
    "fan_out_announcement",
    "publish_announcement",
    "update_announcement",
]
