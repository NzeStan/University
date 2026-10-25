"""SMS provider adapters.

Select one with ``UNIVERSITY["PROVIDERS"]["SMS"]`` and pass its constructor
arguments through ``UNIVERSITY["PROVIDERS"]["SMS_OPTIONS"]``::

    UNIVERSITY = {
        "PROVIDERS": {
            "SMS": "university.core.providers.sms.TermiiSMSProvider",
            "SMS_OPTIONS": {"api_key": env("TERMII_API_KEY"), "sender_id": "Univ"},
        }
    }

Included adapters: Termii, Twilio, Africa's Talking. Implement
:class:`SMSProvider` to add others. Phone numbers are E.164 (``+234…``).
"""

from __future__ import annotations

import base64
import logging
from typing import Protocol

from django.conf import settings

from university.core.crypto import mask_phone
from university.core.providers import http

logger = logging.getLogger("university.sms")


class SMSProvider(Protocol):
    def send(self, to: str, body: str) -> None: ...


class NullSMSProvider:
    """Discards messages. Useful when SMS is disabled."""

    def send(self, to: str, body: str) -> None:
        return None


class ConsoleSMSProvider:
    """Development provider: logs messages only while ``DEBUG`` is on.

    In production it refuses to "deliver" (and never logs message bodies,
    which may contain one-time codes).
    """

    def send(self, to: str, body: str) -> None:
        if settings.DEBUG:
            logger.warning("[dev SMS] to=%s body=%s", mask_phone(to), body)
        else:
            logger.error("ConsoleSMSProvider used with DEBUG=False; SMS to %s not sent.", mask_phone(to))


class TermiiSMSProvider:
    def __init__(
        self,
        api_key: str,
        sender_id: str,
        base_url: str = "https://api.ng.termii.com",
        channel: str = "generic",
    ) -> None:
        self.api_key, self.sender_id = api_key, sender_id
        self.base_url, self.channel = base_url.rstrip("/"), channel

    def send(self, to: str, body: str) -> None:
        http.request(
            "POST",
            f"{self.base_url}/api/sms/send",
            json_body={
                "api_key": self.api_key,
                "to": to.lstrip("+"),
                "from": self.sender_id,
                "sms": body,
                "type": "plain",
                "channel": self.channel,
            },
        )


class TwilioSMSProvider:
    def __init__(self, account_sid: str, auth_token: str, from_number: str) -> None:
        self.account_sid, self.auth_token, self.from_number = account_sid, auth_token, from_number

    def send(self, to: str, body: str) -> None:
        credentials = base64.b64encode(f"{self.account_sid}:{self.auth_token}".encode()).decode()
        http.request(
            "POST",
            f"https://api.twilio.com/2010-04-01/Accounts/{self.account_sid}/Messages.json",
            form={"To": to, "From": self.from_number, "Body": body},
            headers={"Authorization": f"Basic {credentials}"},
        )


class AfricasTalkingSMSProvider:
    def __init__(self, username: str, api_key: str, sender_id: str = "", sandbox: bool = False) -> None:
        self.username, self.api_key, self.sender_id = username, api_key, sender_id
        host = "api.sandbox.africastalking.com" if sandbox else "api.africastalking.com"
        self.url = f"https://{host}/version1/messaging"

    def send(self, to: str, body: str) -> None:
        form = {"username": self.username, "to": to, "message": body}
        if self.sender_id:
            form["from"] = self.sender_id
        http.request("POST", self.url, form=form, headers={"apiKey": self.api_key})
