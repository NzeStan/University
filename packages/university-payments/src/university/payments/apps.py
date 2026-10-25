from __future__ import annotations

from collections.abc import Iterable

from django.utils.translation import gettext_lazy as _

from university.core.declarations import HealthCheck, PermissionDef, RoleDef
from university.core.events import EventBus
from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.payments import __version__


class PaymentsConfig(UniversityAppConfig):
    name = "university.payments"
    label = "university_payments"
    verbose_name = _("University Payments")
    module_name = "payments"
    module_version = __version__
    module_requires = ("core", "users", "permissions", "audit")
    settings_namespace = "PAYMENTS"
    api_prefix = "payments/"
    api_urlconfs = {"v1": "university.payments.api.v1.urls"}

    def get_permissions(self) -> Iterable[PermissionDef]:
        return [
            PermissionDef("payments.view", "View any payment.", sensitive=True),
            PermissionDef("payments.refunds.manage", "Refund payments.", sensitive=True),
            PermissionDef("payments.payouts.manage", "Process payouts to sellers and creators.", sensitive=True),
        ]

    def get_roles(self) -> Iterable[RoleDef]:
        return [
            RoleDef(
                key="finance_officer",
                name="Finance officer",
                scope_type="platform",
                permissions=("payments.*",),
                description="Views payments, issues refunds and processes payouts.",
            )
        ]

    def get_throttle_rates(self) -> dict[str, str | None]:
        return {"payments_checkout": "30/hour", "payments_payout": "10/day"}

    def get_health_checks(self) -> Iterable[HealthCheck]:
        def refunds_flowing() -> bool:
            import datetime as dt

            from django.utils import timezone

            from university.payments.constants import RefundStatus
            from university.payments.models import Refund

            stuck = Refund.objects.filter(
                status=RefundStatus.PENDING, created_at__lt=timezone.now() - dt.timedelta(hours=6)
            )
            return not stuck.exists()

        return [HealthCheck("payments.refunds", refunds_flowing, critical=False)]

    def register_event_handlers(self, bus: EventBus) -> None:
        from university.payments.handlers import HANDLERS

        for name, handler in HANDLERS.items():
            bus.subscribe(name, handler)

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.payments import integrations

        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
