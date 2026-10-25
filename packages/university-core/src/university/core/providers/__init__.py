"""Pluggable provider adapters.

Core never hard-codes a vendor. Each capability is a small protocol with a
default implementation, selected by ``UNIVERSITY["PROVIDERS"]``:

=========  =============================================  =======================
Provider   Protocol                                       Default
=========  =============================================  =======================
EMAIL      :class:`~.email.EmailProvider`                 Django email backend
SMS        :class:`~.sms.SMSProvider`                     console (dev only)
SEARCH     :class:`~.search.SearchBackend`                no-op
SPAM       :class:`~.spam.SpamFilter`                     rule based
=========  =============================================  =======================
"""

from __future__ import annotations

from typing import Any

from university.core.conf import university_settings

_instances: dict[tuple[str, Any], Any] = {}


def _get(name: str) -> Any:
    cls = university_settings.import_from(f"PROVIDERS.{name}")
    options = university_settings.get(f"PROVIDERS.{name}_OPTIONS", {}) or {}
    key = (name, cls)
    if key not in _instances:
        _instances[key] = cls(**options)
    return _instances[key]


def get_email_provider() -> Any:
    return _get("EMAIL")


def get_sms_provider() -> Any:
    return _get("SMS")


def get_search_backend() -> Any:
    return _get("SEARCH")


def get_spam_filter() -> Any:
    return _get("SPAM")


def reset_provider_cache() -> None:
    _instances.clear()
