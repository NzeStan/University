"""Suspicious-login detection (pluggable via ``SECURITY.SUSPICIOUS_LOGIN_DETECTOR``).

The default heuristic flags a login when the device id, network (/24 or /48)
and user agent all differ from the user's recent sessions. Replace it with a
detector backed by geo-IP, device fingerprinting or a risk service by
implementing :class:`SuspiciousLoginDetector`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from university.core.conf import university_settings
from university.core.http import ClientMeta, anonymize_ip


@dataclass(frozen=True)
class LoginRisk:
    reasons: tuple[str, ...] = field(default_factory=tuple)

    @property
    def is_suspicious(self) -> bool:
        return bool(self.reasons)


class SuspiciousLoginDetector(Protocol):
    def assess(self, user: Any, meta: ClientMeta) -> LoginRisk: ...


class HeuristicSuspiciousLoginDetector:
    history = 20

    def assess(self, user: Any, meta: ClientMeta) -> LoginRisk:
        from university.security.models import UserSession

        recent = list(
            UserSession.objects.filter(user=user)
            .order_by("-created_at")
            .values_list("device_id", "ip_address", "user_agent")[: self.history]
        )
        if not recent:
            return LoginRisk()
        network = anonymize_ip(meta.ip_address)
        known_device = bool(meta.device_id) and any(d == meta.device_id for d, _, _ in recent)
        known_network = network is not None and any(anonymize_ip(ip) == network for _, ip, _ in recent)
        known_agent = bool(meta.user_agent) and any(ua == meta.user_agent for _, _, ua in recent)
        if not (known_device or known_network or known_agent):
            return LoginRisk(("new_device_and_network",))
        return LoginRisk()


def get_detector() -> SuspiciousLoginDetector:
    return university_settings.import_from("SECURITY.SUSPICIOUS_LOGIN_DETECTOR")()
