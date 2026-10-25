from typing import Any

BASE = "/api/v1/anonymous"


def post(client: Any, body: str = "Confession: I love the library", **extra: Any) -> dict[str, Any]:
    payload = {"body": body, "visibility": "institution", "audience_id": "inst-1", **extra}
    response = client.post(f"{BASE}/posts/", payload, format="json")
    assert response.status_code == 201, response.json()
    return response.json()


def identifiers(user: Any) -> list[str]:
    """Everything that could identify a user in a response body."""
    values = [str(user.pk), user.pk.hex, user.email, user.handle]
    return [v for v in values if v]
