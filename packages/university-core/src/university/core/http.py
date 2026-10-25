"""HTTP request helpers: trustworthy client IPs and client metadata.

Forwarding headers are attacker-controlled unless set by a proxy you trust.
``SECURITY.TRUSTED_PROXY_COUNT`` declares how many proxies sit in front of
the application; the client address is taken that many hops from the right
of ``X-Forwarded-For``. With the default of ``0`` the header is ignored and
``REMOTE_ADDR`` is used.
"""

from __future__ import annotations

import ipaddress
from dataclasses import dataclass
from typing import Any

from university.core.conf import university_settings

USER_AGENT_MAX_LENGTH = 512
DEVICE_ID_MAX_LENGTH = 128


def _valid_ip(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        return None


def get_client_ip(request: Any) -> str | None:
    meta = request.META
    proxies = int(university_settings.get("SECURITY.TRUSTED_PROXY_COUNT", 0) or 0)
    if proxies > 0:
        header = university_settings.get("SECURITY.CLIENT_IP_HEADER", "HTTP_X_FORWARDED_FOR")
        forwarded = meta.get(header, "")
        hops = [h.strip() for h in forwarded.split(",") if h.strip()]
        if len(hops) >= proxies:
            ip = _valid_ip(hops[-proxies])
            if ip:
                return ip
    return _valid_ip(meta.get("REMOTE_ADDR"))


def anonymize_ip(ip: str | None) -> str | None:
    """Truncate an address to its /24 (IPv4) or /48 (IPv6) network."""
    if not ip:
        return None
    try:
        addr = ipaddress.ip_address(ip)
    except ValueError:
        return None
    prefix = 24 if addr.version == 4 else 48
    return str(ipaddress.ip_network(f"{addr}/{prefix}", strict=False).network_address)


def storable_ip(ip: str | None) -> str | None:
    """Apply the deployment's IP-retention policy before persisting an IP."""
    if university_settings.get("SECURITY.STORE_FULL_IP_ADDRESSES", True):
        return ip
    return anonymize_ip(ip)


def get_user_agent(request: Any) -> str:
    return str(request.META.get("HTTP_USER_AGENT", ""))[:USER_AGENT_MAX_LENGTH]


@dataclass(frozen=True)
class ClientMeta:
    """Client information captured for sessions, audit and risk checks."""

    ip_address: str | None = None
    user_agent: str = ""
    device_id: str = ""
    device_name: str = ""

    @classmethod
    def from_request(cls, request: Any, *, device_id: str = "", device_name: str = "") -> ClientMeta:
        return cls(
            ip_address=get_client_ip(request),
            user_agent=get_user_agent(request),
            device_id=(device_id or "")[:DEVICE_ID_MAX_LENGTH],
            device_name=(device_name or "")[:100],
        )
