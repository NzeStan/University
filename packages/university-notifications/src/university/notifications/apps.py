from __future__ import annotations

import datetime as dt
from collections.abc import Callable, Iterable
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import HealthCheck, RetentionPolicy
from university.core.events import EventBus
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.notifications import __version__


def _days_ago(setting: str, default: int) -> Callable[[], dt.datetime | None]:
    def cutoff() -> dt.datetime | None:
        from university.notifications.conf import notification_settings

        days = notification_settings.get(setting, default)
        return None if days is None else timezone.now() - dt.timedelta(days=int(days))

    return cutoff


class NotificationsConfig(UniversityAppConfig):
    name = "university.notifications"
    label = "university_notifications"
    verbose_name = _("University Notifications")
    module_name = "notifications"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "NOTIFICATIONS"
    api_prefix = ""
    api_urlconfs = {"v1": "university.notifications.api.v1.urls"}

    def ready(self) -> None:
        super().ready()
        from university.notifications import verbs  # noqa: F401  (registers the built-in verbs)

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"notifications_device_register": "30/hour"}

    def get_health_checks(self) -> Iterable[HealthCheck]:
        def deliveries_flowing() -> bool:
            # Unhealthy when deliveries pile up unsent: the task worker is probably down.
            from university.notifications.constants import DeliveryStatus
            from university.notifications.models import Delivery

            stuck = Delivery.objects.filter(
                status__in=[DeliveryStatus.PENDING, DeliveryStatus.SENDING],
                updated_at__lt=timezone.now() - dt.timedelta(hours=1),
            )
            return not stuck[:100].count() >= 100

        return [HealthCheck("notifications.deliveries", deliveries_flowing, critical=False)]

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.notifications.models import Delivery, Notification, PushDevice

        return [
            RetentionPolicy(
                name="notifications.read",
                description="Notifications the recipient has read.",
                setting="NOTIFICATIONS.READ_RETENTION_DAYS",
                cutoff=_days_ago("READ_RETENTION_DAYS", 90),
                purge=lambda c, dry: delete_queryset(Notification.objects.filter(read_at__lt=c), dry),
            ),
            RetentionPolicy(
                name="notifications.all",
                description="Every notification, read or not, after its last activity.",
                setting="NOTIFICATIONS.UNREAD_RETENTION_DAYS",
                cutoff=_days_ago("UNREAD_RETENTION_DAYS", 365),
                purge=lambda c, dry: delete_queryset(Notification.objects.filter(last_activity_at__lt=c), dry),
            ),
            RetentionPolicy(
                name="notifications.deliveries",
                description="Delivery attempt records (status, reason, timestamps).",
                setting="NOTIFICATIONS.DELIVERY_RETENTION_DAYS",
                cutoff=_days_ago("DELIVERY_RETENTION_DAYS", 30),
                purge=lambda c, dry: delete_queryset(Delivery.objects.filter(created_at__lt=c), dry),
            ),
            RetentionPolicy(
                name="notifications.disabled_devices",
                description="Push devices that were unregistered, replaced or rejected by the provider.",
                setting="NOTIFICATIONS.DISABLED_DEVICE_RETENTION_DAYS",
                cutoff=_days_ago("DISABLED_DEVICE_RETENTION_DAYS", 30),
                purge=lambda c, dry: delete_queryset(PushDevice.objects.filter(disabled_at__lt=c), dry),
            ),
        ]

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.notifications.conf import notification_settings
        from university.notifications.handlers import HANDLERS, handle_event

        run_async = bool(notification_settings.get("ASYNC_HANDLERS", False))
        for name in HANDLERS:
            bus.subscribe(name, handle_event, run_async=run_async)

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.notifications import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)

    def get_permissions(self) -> Iterable[Any]:
        return []
