"""Minimal outbound HTTP client for provider adapters.

Uses only the standard library so adapters add no dependencies. Requests go
only to fixed, operator-configured provider URLs (never user-supplied URLs),
use HTTPS, enforce timeouts and do not follow redirects.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Mapping
from typing import Any

from university.core.exceptions import ProviderError

DEFAULT_TIMEOUT = 10


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args: Any, **kwargs: Any) -> None:
        return None


_opener = urllib.request.build_opener(_NoRedirect)


def request(
    method: str,
    url: str,
    *,
    json_body: Any = None,
    form: Mapping[str, str] | None = None,
    headers: Mapping[str, str] | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> Any:
    if urllib.parse.urlsplit(url).scheme != "https":
        raise ProviderError("Provider URLs must use HTTPS.")
    data: bytes | None = None
    all_headers = {"Accept": "application/json", **(headers or {})}
    if json_body is not None:
        data = json.dumps(json_body).encode()
        all_headers["Content-Type"] = "application/json"
    elif form is not None:
        data = urllib.parse.urlencode(form).encode()
        all_headers["Content-Type"] = "application/x-www-form-urlencoded"
    req = urllib.request.Request(url, data=data, headers=all_headers, method=method)  # noqa: S310
    try:
        with _opener.open(req, timeout=timeout) as resp:
            raw = resp.read()
    except urllib.error.HTTPError as exc:
        raise ProviderError(code="provider_http_error", details={"status": exc.code}) from exc
    except (urllib.error.URLError, TimeoutError) as exc:
        raise ProviderError(code="provider_unreachable") from exc
    if not raw:
        return None
    try:
        return json.loads(raw)
    except ValueError:
        return raw.decode("utf-8", "replace")
