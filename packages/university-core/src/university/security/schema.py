"""drf-spectacular extensions describing University authentication schemes."""

from __future__ import annotations

from typing import Any

from drf_spectacular.extensions import OpenApiAuthenticationExtension

from university.core.conf import university_settings


class JWTAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "university.security.authentication.JWTAuthentication"
    name = "BearerAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "http",
            "scheme": "bearer",
            "bearerFormat": "JWT",
            "description": "Short-lived access token from /auth/login/ or /auth/token/refresh/.",
        }


class APIKeyAuthenticationScheme(OpenApiAuthenticationExtension):
    target_class = "university.security.authentication.APIKeyAuthentication"
    name = "ApiKeyAuth"

    def get_security_definition(self, auto_schema: Any) -> dict[str, Any]:
        return {
            "type": "apiKey",
            "in": "header",
            "name": university_settings.get("AUTH.API_KEYS.HEADER", "X-API-Key"),
            "description": "API key for trusted integrations, limited to its permission scopes.",
        }
