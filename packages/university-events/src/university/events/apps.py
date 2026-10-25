from __future__ import annotations

import datetime as dt
from collections.abc import Iterable
from typing import Any

from django.utils import timezone
from django.utils.translation import gettext_lazy as _

from university.core.declarations import PermissionDef, RetentionPolicy, RoleDef, ScopeTypeDef
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.events import __version__
from university.events.constants import EVENT_SCOPE


class EventsConfig(UniversityAppConfig):
    name = "university.events"
    label = "university_events"
    verbose_name = _("University Events")
    module_name = "events"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "EVENTS"
    api_prefix = ""
    api_urlconfs = {"v1": "university.events.api.v1.urls"}

    def get_scope_types(self) -> Iterable[ScopeTypeDef]:
        from university.events.integrations import event_parents

        return [ScopeTypeDef(EVENT_SCOPE, "A single event.", parent_resolver=event_parents)]

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef(
                "events.create", "Host personal events (under the 'permission' creation policy).", scopes=("*",)
            ),
            PermissionDef(
                "events.manage",
                "Host and manage events, tickets, schedules and registrations within a scope.",
                scopes=("*",),
            ),
            PermissionDef("events.checkin", "Check attendees in and see attendee lists.", scopes=("*",)),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="events_manager",
                name="Events manager",
                scope_type="*",
                permissions=("events.*",),
                description="Hosts and manages every event within a scope (e.g. an institution's events office).",
            )
        ]

    def get_content_adapters(self) -> list[Any]:
        from university.events.content import EventAdapter

        return [EventAdapter()]

    def get_payable_adapters(self) -> list[Any]:
        from university.events.payables import RegistrationPayable

        return [RegistrationPayable()]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {
            "events_create": "10/day",
            "events_venue_create": "20/day",
            "events_register": "30/hour",
            "events_checkin": "1200/hour",
        }

    def get_retention_policies(self) -> Iterable[RetentionPolicy]:
        from university.core.retention import delete_queryset
        from university.events.conf import events_settings
        from university.events.models import Registration

        def cutoff() -> dt.datetime | None:
            days = events_settings.get("REGISTRATION_RETENTION_DAYS", 730)
            return None if days is None else timezone.now() - dt.timedelta(days=int(days))

        return [
            RetentionPolicy(
                name="events.past_registrations",
                description="Registrations (attendance history) for events that ended long ago.",
                setting="EVENTS.REGISTRATION_RETENTION_DAYS",
                cutoff=cutoff,
                purge=lambda c, dry: delete_queryset(Registration.objects.filter(event__ends_at__lt=c), dry),
            )
        ]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.events import integrations

        hooks.register(Hook.PERMISSIONS_IMPLICIT_GRANTS, integrations.implicit_grants)
        hooks.register(Hook.PERMISSIONS_IMPLICIT_SCOPES, integrations.implicit_scopes)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
