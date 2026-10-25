from __future__ import annotations

from typing import Any

from django.core.checks import Tags, Warning, register


@register(Tags.security, deploy=True)
def check_identity_keys(app_configs: Any = None, **kwargs: Any) -> list[Warning]:
    from university.anonymous.identity import identity_keys_configured

    if identity_keys_configured():
        return []
    return [
        Warning(
            "Anonymous identities are encrypted with a key derived from SECRET_KEY/HMAC_KEY.",
            hint="Set UNIVERSITY['ANONYMOUS']['IDENTITY_KEYS'] to dedicated Fernet keys "
            "(cryptography.fernet.Fernet.generate_key()) held outside the database.",
            id="university_anonymous.W001",
        )
    ]
