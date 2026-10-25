"""External social platforms, behind one small protocol.

Core and this module never hard-code a platform. Each one is a
:class:`SocialProvider` configured in ``CREATOR.PROVIDERS``::

    "PROVIDERS": {
        "youtube": {
            "label": "YouTube",
            "url": "https://www.youtube.com/@{handle}",
            "class": "university.creator.providers.YouTubeProvider",
            "options": {"api_key": os.environ["YOUTUBE_API_KEY"]},
        },
        "tiktok": None,  # remove a default platform
    }

Providers without an API (the default :class:`ManualProvider`) still work:
links are built from a URL template and ownership is confirmed by a reviewer.
Providers that can look profiles up verify ownership automatically with a
challenge code the creator places in their public bio, and keep follower
counts fresh. No platform passwords or OAuth tokens are stored.
"""

from __future__ import annotations

import re
import urllib.parse
from dataclasses import dataclass
from typing import Any, Protocol

from django.utils.module_loading import import_string

from university.core.exceptions import ProviderError, ValidationError
from university.core.providers.http import request
from university.creator.conf import creator_settings

HANDLE_RE = re.compile(r"^[A-Za-z0-9._\-]{1,100}$")


@dataclass(frozen=True)
class ExternalProfile:
    external_id: str
    handle: str
    display_name: str = ""
    url: str = ""
    follower_count: int | None = None
    bio: str = ""


class SocialProvider(Protocol):
    key: str
    label: str
    #: Whether :meth:`fetch_profile` works (enables challenge verification and syncing).
    supports_lookup: bool

    def profile_url(self, handle: str) -> str: ...

    def fetch_profile(self, handle: str) -> ExternalProfile | None: ...


class ManualProvider:
    """A platform without API access: links only, reviewer-confirmed ownership."""

    supports_lookup = False

    def __init__(self, key: str, label: str = "", url: str = "", **_: Any) -> None:
        self.key = key
        self.label = label or key
        self.url_template = url

    def profile_url(self, handle: str) -> str:
        if not self.url_template:
            return ""
        return self.url_template.format(handle=urllib.parse.quote(handle, safe=""))

    def fetch_profile(self, handle: str) -> ExternalProfile | None:
        return None


class YouTubeProvider(ManualProvider):
    """YouTube Data API v3 (a server API key; read-only public data)."""

    supports_lookup = True
    API = "https://www.googleapis.com/youtube/v3/channels"

    def __init__(self, key: str, label: str = "YouTube", url: str = "", *, api_key: str = "", **_: Any) -> None:
        super().__init__(key, label, url or "https://www.youtube.com/@{handle}")
        if not api_key:
            raise ValueError("YouTubeProvider needs an api_key.")
        self.api_key = api_key

    def fetch_profile(self, handle: str) -> ExternalProfile | None:
        query = urllib.parse.urlencode(
            {"part": "snippet,statistics", "forHandle": f"@{handle.lstrip('@')}", "key": self.api_key}
        )
        data = request("GET", f"{self.API}?{query}")
        items = (data.get("items") if isinstance(data, dict) else None) or []
        if not items:
            return None
        item = items[0]
        snippet, stats = item.get("snippet") or {}, item.get("statistics") or {}
        hidden = stats.get("hiddenSubscriberCount")
        return ExternalProfile(
            external_id=str(item.get("id", "")),
            handle=handle.lstrip("@"),
            display_name=str(snippet.get("title", ""))[:150],
            url=self.profile_url(handle.lstrip("@")),
            follower_count=None if hidden else int(stats.get("subscriberCount", 0) or 0),
            bio=str(snippet.get("description", "")),
        )


def normalize_handle(handle: str) -> str:
    handle = (handle or "").strip().lstrip("@")
    if not HANDLE_RE.match(handle):
        raise ValidationError(details={"handle": ["Enter the account's handle, without spaces or a URL."]})
    return handle


_cache: dict[str, tuple[Any, SocialProvider]] = {}


def providers() -> dict[str, SocialProvider]:
    out: dict[str, SocialProvider] = {}
    for key, conf in (creator_settings.get("PROVIDERS") or {}).items():
        if not conf:
            continue
        cached = _cache.get(key)
        if cached is None or cached[0] != conf:
            cls = import_string(conf["class"]) if conf.get("class") else ManualProvider
            instance = cls(key, label=conf.get("label", key), url=conf.get("url", ""), **(conf.get("options") or {}))
            cached = (conf, instance)
            _cache[key] = cached
        out[key] = cached[1]
    return out


def get_provider(key: str) -> SocialProvider:
    provider = providers().get(key)
    if provider is None:
        raise ValidationError(details={"provider": ["Unsupported platform."]})
    return provider


def safe_fetch(provider: SocialProvider, handle: str) -> ExternalProfile | None:
    """Look a profile up; provider outages surface as a retryable error code."""
    if not provider.supports_lookup:
        return None
    try:
        return provider.fetch_profile(handle)
    except ProviderError:
        raise
    except Exception as exc:  # A misbehaving adapter must not break the request.
        raise ProviderError(code="social_provider_failed") from exc
