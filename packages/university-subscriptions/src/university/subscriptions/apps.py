from __future__ import annotations

from typing import Any

from django.utils.translation import gettext_lazy as _

from university.core.hooks import Hook, HookRegistry
from university.core.modules import UniversityAppConfig
from university.subscriptions import __version__


class SubscriptionsConfig(UniversityAppConfig):
    name = "university.subscriptions"
    label = "university_subscriptions"
    verbose_name = _("University Subscriptions")
    module_name = "subscriptions"
    module_version = __version__
    module_requires = ("core", "users", "audit")
    settings_namespace = "SUBSCRIPTIONS"
    api_prefix = "subscriptions/"
    api_urlconfs = {"v1": "university.subscriptions.api.v1.urls"}

    def get_payable_adapters(self) -> list[Any]:
        from university.subscriptions.payables import PeriodPayable

        return [PeriodPayable()]

    def register_hooks(self, hooks: HookRegistry) -> None:
        from university.subscriptions import integrations, services

        hooks.register(Hook.USER_ENTITLEMENTS, services.user_entitlements)
        hooks.register(Hook.USER_PUBLIC_PROFILE, integrations.public_profile)
        hooks.register(Hook.USER_EXPORT_DATA, integrations.export_data)
        hooks.register(Hook.USER_PURGE, integrations.purge)
