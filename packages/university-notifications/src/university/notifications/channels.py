"""Delivery channels: email, push and SMS.

A channel decides whether it can reach a person (:meth:`BaseChannel.is_available`)
and sends one rendered notification. Raising marks the attempt as failed and
schedules a retry. Messages contain the rendered title and a link only —
never post bodies or other content.

Register custom channels (e.g. WhatsApp) in ``NOTIFICATIONS.CHANNELS``.
"""

from __future__ import annotations

from typing import Any

from django.utils import timezone
from django.utils.translation import gettext as _

from university.core.exceptions import ProviderError
from university.notifications.conf import notification_settings
from university.notifications.rendering import Rendered

EMAIL_TEMPLATE = "university/notifications/email/notification"
DIGEST_TEMPLATE = "university/notifications/email/digest"


class BaseChannel:
    name = ""

    def is_available(self, user: Any) -> bool:
        raise NotImplementedError

    def send(self, user: Any, notification: Any, rendered: Rendered) -> None:
        raise NotImplementedError


def _email_context(**extra: Any) -> dict[str, Any]:
    return {
        "site_name": notification_settings.get("SITE_NAME"),
        "preferences_url": notification_settings.get("PREFERENCES_URL"),
        "list_url": notification_settings.get("LIST_URL"),
        **extra,
    }


def send_email(user: Any, template: str, context: dict[str, Any], category: str) -> None:
    from university.core.providers import get_email_provider
    from university.core.providers.email import EmailMessage, render_email

    message = render_email(template, _email_context(**context), [user.email])
    headers = {
        "X-University-Category": category,
        "List-Unsubscribe": f"<{notification_settings.get('PREFERENCES_URL')}>",
    }
    get_email_provider().send(
        EmailMessage(
            to=message.to,
            subject=message.subject,
            body=message.body,
            html_body=message.html_body,
            headers=headers,
        )
    )


class EmailChannel(BaseChannel):
    name = "email"

    def is_available(self, user: Any) -> bool:
        return bool(user.email and user.email_verified_at)

    def send(self, user: Any, notification: Any, rendered: Rendered) -> None:
        send_email(user, EMAIL_TEMPLATE, {"title": rendered.title, "url": rendered.url}, notification.category)


class PushChannel(BaseChannel):
    name = "push"

    def devices(self, user: Any) -> Any:
        import datetime as dt

        stale = timezone.now() - dt.timedelta(days=int(notification_settings.get("DEVICE_STALE_DAYS", 270)))
        return user.push_devices.filter(disabled_at__isnull=True, last_seen_at__gte=stale)

    def is_available(self, user: Any) -> bool:
        return self.devices(user).exists()

    def send(self, user: Any, notification: Any, rendered: Rendered) -> None:
        from university.notifications.push import PushMessage, get_push_provider

        devices = list(self.devices(user))
        title = rendered.title if notification_settings.get("PUSH_PREVIEWS", True) else _("You have a new notification")
        result = get_push_provider().send(
            PushMessage(
                tokens=[d.token for d in devices],
                title=title,
                data={"notification_id": str(notification.pk), "category": notification.category, "url": rendered.url},
                collapse_key=str(notification.pk),
            )
        )
        if result.invalid_tokens:
            invalid = set(result.invalid_tokens)
            ids = [d.pk for d in devices if d.token in invalid]
            user.push_devices.filter(pk__in=ids).update(disabled_at=timezone.now(), disabled_reason="unregistered")
        if result.sent == 0 and result.retry:
            raise ProviderError(code="push_failed")


class SMSChannel(BaseChannel):
    name = "sms"

    def is_available(self, user: Any) -> bool:
        return bool(user.phone_number and user.phone_verified_at)

    def send(self, user: Any, notification: Any, rendered: Rendered) -> None:
        from university.core.providers import get_sms_provider

        site = notification_settings.get("SITE_NAME")
        get_sms_provider().send(user.phone_number, f"{site}: {rendered.title}"[:300])


_channels: dict[str, tuple[Any, BaseChannel]] = {}


def get_channel(name: str) -> BaseChannel | None:
    path = (notification_settings.get("CHANNELS") or {}).get(name)
    if not path:
        return None
    cached = _channels.get(name)
    if cached is None or cached[0] != path:
        from django.utils.module_loading import import_string

        cached = (path, import_string(path)())
        _channels[name] = cached
    return cached[1]


def enabled_channels() -> list[str]:
    return [name for name, path in (notification_settings.get("CHANNELS") or {}).items() if path]
