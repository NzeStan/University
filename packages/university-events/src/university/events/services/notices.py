"""Attendee notices: one ids-only event per registrant.

Notifications (or any other consumer) subscribe to ``events.attendee.notice``;
this module never imports them. Fan-out runs on the task backend.
"""

from __future__ import annotations

import datetime as dt

from django.utils import timezone

from university.core.events import publish
from university.core.tasks import enqueue, task
from university.events import events
from university.events.conf import events_settings
from university.events.constants import ACTIVE_STATUSES, EventStatus, NoticeKind, RegistrationStatus
from university.events.models import Event, Registration


def notify_attendees(event: Event, kind: str) -> None:
    enqueue(fan_out_notice, str(event.pk), str(kind))


@task(name="university.events.fan_out_notice")
def fan_out_notice(event_id: str, kind: str) -> int:
    rows = Registration.objects.filter(event_id=event_id, status__in=ACTIVE_STATUSES).values_list("pk", "user_id")
    count = 0
    for registration_id, user_id in rows.iterator(chunk_size=500):
        publish(
            events.ATTENDEE_NOTICE,
            {"event_id": event_id, "registration_id": registration_id, "user_id": user_id, "kind": kind},
        )
        count += 1
    return count


@task(name="university.events.send_reminders")
def send_reminders() -> int:
    """Remind confirmed attendees of events starting within ``REMINDER_HOURS``. Safe to run often."""
    now = timezone.now()
    horizon = now + dt.timedelta(hours=int(events_settings.get("REMINDER_HOURS", 24)))
    due = Registration.objects.filter(
        status=RegistrationStatus.CONFIRMED,
        reminder_sent_at__isnull=True,
        event__status=EventStatus.PUBLISHED,
        event__hidden_at__isnull=True,
        event__deleted_at__isnull=True,
        event__starts_at__gt=now,
        event__starts_at__lte=horizon,
    ).values_list("pk", "event_id", "user_id")
    sent = 0
    for registration_id, event_id, user_id in list(due):
        # Claim each reminder so overlapping runs never send twice.
        if Registration.objects.filter(pk=registration_id, reminder_sent_at__isnull=True).update(reminder_sent_at=now):
            publish(
                events.ATTENDEE_NOTICE,
                {
                    "event_id": event_id,
                    "registration_id": registration_id,
                    "user_id": user_id,
                    "kind": NoticeKind.REMINDER,
                },
            )
            sent += 1
    return sent
