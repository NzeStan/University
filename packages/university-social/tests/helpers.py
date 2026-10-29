from __future__ import annotations

from typing import Any

from tests.audience.apps import MEMBERS

BASE = "/api/v1/social"
PNG = b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x02\x00\x00\x00\x90wS\xde\x00\x00\x00\x0cIDATx\xdac\xc8\xd5\xb8\t\x00\x02t\x01o\xfbJ\xd2\xe1\x00\x00\x00\x00IEND\xaeB`\x82"  # A real 1x1 PNG: decodes with or without Pillow.


def make_post(client: Any, body: str = "Hello campus", **extra: Any) -> dict[str, Any]:
    response = client.post(f"{BASE}/posts/", {"body": body, **extra}, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def join_audience(user: Any, scope_type: str, scope_id: str) -> None:
    MEMBERS.setdefault(str(user.pk), []).append((scope_type, scope_id))
    if hasattr(user, "_university_member_scopes"):
        del user._university_member_scopes
