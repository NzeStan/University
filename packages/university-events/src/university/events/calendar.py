"""iCalendar (RFC 5545) export for one event."""

from __future__ import annotations

import datetime as dt
from typing import Any

from django.utils import timezone

from university.events.conf import events_settings
from university.events.constants import EventStatus


def _escape(value: str) -> str:
    return (
        value.replace("\\", "\\\\").replace(";", "\\;").replace(",", "\\,").replace("\r\n", "\\n").replace("\n", "\\n")
    )


def _fold(line: str) -> str:
    """Fold lines longer than 75 octets (continuations start with a space)."""
    out, current = [], b""
    for ch in line:
        encoded = ch.encode()
        if len(current) + len(encoded) > (75 if not out else 74):
            out.append(current.decode())
            current = b""
        current += encoded
    out.append(current.decode())
    return "\r\n ".join(out)


def _stamp(value: dt.datetime) -> str:
    return value.astimezone(dt.UTC).strftime("%Y%m%dT%H%M%SZ")


def event_url(event: Any) -> str:
    return str(events_settings.get("EVENT_URL")).format(id=event.pk, slug=event.slug)


def build_ics(event: Any, *, include_online_url: bool = False) -> str:
    location = ""
    if event.venue_id:
        venue = event.venue
        location = ", ".join(p for p in (venue.name, venue.address, venue.city, venue.country) if p)
    if event.location_details:
        location = f"{location} ({event.location_details})" if location else event.location_details
    description = event.summary or ""
    url = event_url(event)
    if include_online_url and event.online_url:
        description = f"{description}\n\nJoin online: {event.online_url}".strip()
    full_description = f"{description}\n\n{url}".strip()
    lines = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//University Platform//Events//EN",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:{event.pk}@university-events",
        f"DTSTAMP:{_stamp(timezone.now())}",
        f"DTSTART:{_stamp(event.starts_at)}",
        f"DTEND:{_stamp(event.ends_at)}",
        f"SEQUENCE:{int(event.updated_at.timestamp())}",
        f"SUMMARY:{_escape(event.title)}",
        f"DESCRIPTION:{_escape(full_description)}",
        f"URL:{url}",
        f"STATUS:{'CANCELLED' if event.status == EventStatus.CANCELLED else 'CONFIRMED'}",
    ]
    if location:
        lines.append(f"LOCATION:{_escape(location)}")
    lines += ["END:VEVENT", "END:VCALENDAR"]
    return "\r\n".join(_fold(line) for line in lines) + "\r\n"
