from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import RetentionPolicy
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.messaging import __version__


class MessagingConfig(UniversityAppConfig):
    name = "university.messaging"
    label = "university_messaging"
    verbose_name = _("University Messaging")
    module_name = "messaging"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "MESSAGING"
    api_prefix = "messaging/"
    api_urlconfs = {"v1": "university.messaging.api.v1.urls"}

    def get_content_adapters(self) -> list[Any]:
        from university.messaging.content import MessageAdapter

        return [MessageAdapter()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {
            "messaging_new_conversation": "30/day",
            "messaging_message": "120/minute",
            "messaging_send": "120/minute",
        }

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.messaging.conf import messaging_settings
        from university.messaging.models import Message, MessageStatus

        def cutoff() -> dt.datetime | None:
            days = messaging_settings.get("DELETED_RETENTION_DAYS")
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="messaging.deleted_messages",
                description="Tombstones of messages their senders deleted.",
                setting="MESSAGING.DELETED_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(
                    Message.objects.filter(status=MessageStatus.DELETED, deleted_at__lt=c), dry
                ),
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.messaging import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
