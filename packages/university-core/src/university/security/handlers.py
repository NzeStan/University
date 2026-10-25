"""Event handlers of the security app (auto-imported on ready)."""

from __future__ import annotations

from django.contrib.auth import get_user_model

from university.core.conf import university_settings
from university.core.crypto import mask_email
from university.core.events import Event, subscribe
from university.core.http import anonymize_ip
from university.core.providers.email import send_templated_email
from university.security import events


@subscribe(events.LOGIN_SUSPICIOUS)
def send_login_alert(event: Event) -> None:
    """Email the account owner about a sign-in from a new device/network."""
    if not university_settings.get("SECURITY.SEND_LOGIN_ALERT_EMAILS", True):
        return
    from university.security.models import UserSession
    from university.users.services.preferences import get_security_settings

    user = get_user_model().objects.filter(pk=event.payload.get("user_id")).first()
    if user is None or not get_security_settings(user).login_alerts_enabled:
        return
    session = UserSession.objects.filter(pk=event.payload.get("session_id")).first()
    send_templated_email(
        "university/security/email/login_alert",
        {
            "display_name": user.get_short_name(),
            "email": mask_email(user.email),
            "when": event.occurred_at,
            "network": anonymize_ip(session.ip_address) if session else None,
            "device": (session.device_name or session.user_agent[:120]) if session else "",
        },
        [user.email],
    )
