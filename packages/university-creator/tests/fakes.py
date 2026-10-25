"""A lookup-capable social provider for tests."""

from __future__ import annotations

from typing import Any

from university.creator.providers import ExternalProfile, ManualProvider

#: handle -> ExternalProfile
PROFILES: dict[str, ExternalProfile] = {}


class FakeProvider(ManualProvider):
    supports_lookup = True

    def __init__(self, key: str, label: str = "", url: str = "", **_: Any) -> None:
        super().__init__(key, label or "FakeTube", url or "https://faketube.example/{handle}")

    def fetch_profile(self, handle: str) -> ExternalProfile | None:
        return PROFILES.get(handle.lower())
