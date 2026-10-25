"""Push providers.

Select one with ``NOTIFICATIONS.PUSH_PROVIDER`` (options in
``PUSH_PROVIDER_OPTIONS``):

* :class:`NullPushProvider` — sends nothing (default; development and tests).
* :class:`FCMPushProvider` — Firebase Cloud Messaging HTTP v1 (Android, iOS
  through APNs, and web), authenticated with a service account.
* :class:`ExpoPushProvider` — Expo's push service, for Expo/React Native apps.

Implement :class:`PushProvider` for anything else. Providers report tokens
that are no longer registered so the device is disabled instead of retried.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from university.core.exceptions import ProviderError
from university.core.providers.http import request
from university.notifications.conf import notification_settings

logger = logging.getLogger("university.notifications.push")


@dataclass(frozen=True)
class PushMessage:
    tokens: Sequence[str]
    title: str
    body: str = ""
    #: String values only; never content or secrets.
    data: Mapping[str, str] = field(default_factory=dict)
    #: Collapse key: newer pushes for the same notification replace older ones.
    collapse_key: str = ""


@dataclass
class PushResult:
    sent: int = 0
    #: Tokens the provider says are invalid or unregistered.
    invalid_tokens: list[str] = field(default_factory=list)
    #: True when some failures were transient and the delivery should be retried.
    retry: bool = False


class PushProvider(Protocol):
    def send(self, message: PushMessage) -> PushResult: ...


class NullPushProvider:
    """Records nothing and sends nothing."""

    def send(self, message: PushMessage) -> PushResult:
        return PushResult(sent=len(message.tokens))


class FCMPushProvider:
    """Firebase Cloud Messaging (HTTP v1).

    Options: ``project_id`` plus either ``credentials_file`` (a service account
    JSON file) or ``client_email`` and ``private_key``. Keep credentials in the
    environment or a secret store, never in source control.
    """

    TOKEN_URI = "https://oauth2.googleapis.com/token"  # noqa: S105 - an endpoint, not a secret
    SCOPE = "https://www.googleapis.com/auth/firebase.messaging"

    def __init__(
        self,
        project_id: str,
        *,
        credentials_file: str | None = None,
        client_email: str | None = None,
        private_key: str | None = None,
        timeout: int = 10,
    ) -> None:
        if credentials_file:
            with open(credentials_file, encoding="utf-8") as fh:
                info = json.load(fh)
            client_email, private_key = info["client_email"], info["private_key"]
        if not (project_id and client_email and private_key):
            raise ValueError("FCMPushProvider needs project_id and service account credentials.")
        self.project_id = project_id
        self.client_email = client_email
        self.private_key = private_key
        self.timeout = timeout
        self._token: tuple[str, float] | None = None
        self._lock = threading.Lock()

    def _access_token(self, *, refresh: bool = False) -> str:
        with self._lock:
            if not refresh and self._token and self._token[1] > time.time() + 60:
                return self._token[0]
            import jwt

            now = int(time.time())
            assertion = jwt.encode(
                {"iss": self.client_email, "scope": self.SCOPE, "aud": self.TOKEN_URI, "iat": now, "exp": now + 3600},
                self.private_key,
                algorithm="RS256",
            )
            data = request(
                "POST",
                self.TOKEN_URI,
                form={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": assertion},
                timeout=self.timeout,
            )
            if not isinstance(data, dict) or "access_token" not in data:
                raise ProviderError(code="push_auth_failed")
            self._token = (data["access_token"], time.time() + int(data.get("expires_in", 3600)))
            return self._token[0]

    def _payload(self, token: str, message: PushMessage) -> dict[str, Any]:
        msg: dict[str, Any] = {
            "token": token,
            "notification": {"title": message.title, **({"body": message.body} if message.body else {})},
            "data": {k: str(v) for k, v in message.data.items()},
            "android": {"priority": "high"},
            "apns": {"headers": {"apns-priority": "10"}},
        }
        if message.collapse_key:
            msg["android"]["collapse_key"] = message.collapse_key
            msg["apns"]["headers"]["apns-collapse-id"] = message.collapse_key[:64]
        return {"message": msg}

    def send(self, message: PushMessage) -> PushResult:
        result = PushResult()
        url = f"https://fcm.googleapis.com/v1/projects/{self.project_id}/messages:send"
        for token in message.tokens:
            for attempt in range(2):
                headers = {"Authorization": f"Bearer {self._access_token(refresh=attempt > 0)}"}
                try:
                    request("POST", url, json_body=self._payload(token, message), headers=headers, timeout=self.timeout)
                    result.sent += 1
                except ProviderError as exc:
                    status = exc.details.get("status")
                    if status == 401 and attempt == 0:
                        continue  # Expired access token: refresh once.
                    if status in (400, 404):
                        result.invalid_tokens.append(token)  # UNREGISTERED / INVALID_ARGUMENT
                    else:
                        result.retry = True
                        logger.warning("FCM send failed (%s)", exc.code)
                break
        return result


class ExpoPushProvider:
    """Expo push service. Option: ``access_token`` (when enhanced security is on)."""

    URL = "https://exp.host/--/api/v2/push/send"
    BATCH = 100

    def __init__(self, access_token: str | None = None, timeout: int = 10) -> None:
        self.access_token = access_token
        self.timeout = timeout

    def send(self, message: PushMessage) -> PushResult:
        result = PushResult()
        headers = {"Authorization": f"Bearer {self.access_token}"} if self.access_token else {}
        tokens = list(message.tokens)
        for i in range(0, len(tokens), self.BATCH):
            batch = tokens[i : i + self.BATCH]
            body = [
                {
                    "to": token,
                    "title": message.title,
                    "body": message.body,
                    "data": dict(message.data),
                    "priority": "high",
                    **({"collapseId": message.collapse_key} if message.collapse_key else {}),
                }
                for token in batch
            ]
            try:
                response = request("POST", self.URL, json_body=body, headers=headers, timeout=self.timeout)
            except ProviderError as exc:
                logger.warning("Expo push failed (%s)", exc.code)
                result.retry = True
                continue
            tickets = response.get("data", []) if isinstance(response, dict) else []
            for token, ticket in zip(batch, tickets, strict=False):
                if ticket.get("status") == "ok":
                    result.sent += 1
                elif (ticket.get("details") or {}).get("error") == "DeviceNotRegistered":
                    result.invalid_tokens.append(token)
                else:
                    result.retry = True
        return result


_provider: tuple[Any, Any] | None = None


def get_push_provider() -> PushProvider:
    global _provider
    cls = notification_settings.import_from("PUSH_PROVIDER")
    if _provider is None or _provider[0] is not cls:
        options = notification_settings.get("PUSH_PROVIDER_OPTIONS", {}) or {}
        _provider = (cls, cls(**options))
    return _provider[1]


def reset_push_provider() -> None:
    global _provider
    _provider = None
