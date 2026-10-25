from __future__ import annotations

from typing import Any

from tests.audience.apps import MEMBERS

BASE = "/api/v1/social"
PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


def make_post(client: Any, body: str = "Hello campus", **extra: Any) -> dict[str, Any]:
    response = client.post(f"{BASE}/posts/", {"body": body, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def join_audience(user: Any, scope_type: str, scope_id: str) -> None:
    MEMBERS.setdefault(str(user.pk), []).append((scope_type, scope_id))
    if hasattr(user, "_university_member_scopes"):
        del user._university_member_scopes
