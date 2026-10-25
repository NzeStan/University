"""Render notifications for a viewer at read time.

Nothing user-written is stored with a notification. Titles combine the verb's
translatable text with the actor's *current* name and, for ``{target}``, a
label the viewer is allowed to see (through Core content adapters).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from django.core.exceptions import ImproperlyConfigured
from django.utils.translation import gettext as _

from university.notifications.conf import notification_settings
from university.notifications.verbs import get_verb


class _Values(dict):
    def __missing__(self, key: str) -> str:
        return ""


@dataclass(frozen=True)
class Rendered:
    title: str
    url: str


def actor_name(user: Any) -> str:
    if user is None or not user.is_active or getattr(user, "anonymized_at", None):
        return _("Someone")
    if user.display_name:
        return user.display_name
    return f"@{user.handle}" if user.handle else _("Someone")


def _adapter(target_type: str) -> Any:
    from university.core.registry import registry

    return registry.content_adapters.get(target_type) if target_type else None


def target_available(notification: Any, viewer: Any) -> bool | None:
    """Whether the viewer can still open the target (``None`` when unknown)."""
    adapter = _adapter(notification.target_type)
    if adapter is None:
        return None
    try:
        return bool(adapter.can_view(viewer, notification.target_id))
    except Exception:
        return False


def target_label(notification: Any, viewer: Any) -> str:
    adapter = _adapter(notification.target_type)
    if adapter is None:
        return ""
    try:
        if not adapter.can_view(viewer, notification.target_id):
            return ""
        ref = adapter.resolve(notification.target_id)
    except Exception:
        return ""
    if ref is None or ref.is_anonymous or not ref.excerpt:
        return ""
    return ref.excerpt.strip().splitlines()[0][:80]


def render_title(notification: Any, viewer: Any) -> str:
    try:
        verb = get_verb(notification.verb)
    except ImproperlyConfigured:  # The module that defined it was removed.
        return _("You have a new notification.")
    many = verb.aggregates and notification.actor_count > 1
    text = str(verb.aggregate_text if many else verb.text)
    values = _Values(others=max(notification.actor_count - 1, 0))
    if verb.show_actor:
        values["actor"] = actor_name(notification.actor)
    if "{target}" in text:
        values["target"] = target_label(notification, viewer) or str(verb.target_fallback or "")
    data = notification.data or {}
    for key in verb.text_data:
        values[key] = str(data.get(key, ""))[:40]
    return text.format_map(values)


def open_url(notification: Any) -> str:
    return str(notification_settings.get("OPEN_URL")).format(id=notification.pk)


def render(notification: Any, viewer: Any) -> Rendered:
    return Rendered(title=render_title(notification, viewer), url=open_url(notification))
