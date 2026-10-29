"""How every module shows a person: one shape everywhere.

    from university.users.refs import PersonRefSerializer, person_ref

    {"id": "…", "handle": "ada", "display_name": "Ada Obi", "avatar_url": "https://…/avatar.webp"}

Use ``person_ref(user)`` when building responses and ``PersonRefSerializer`` in schemas, so clients
can rely on the same fields (including the profile photo) for authors, sellers, hosts, actors…
"""

from __future__ import annotations

from typing import Any

from rest_framework import serializers

from university.users.services.avatars import avatar_url


def person_ref(user: Any) -> dict[str, Any] | None:
    if user is None:
        return None
    return {
        "id": str(user.pk),
        "handle": user.handle,
        "display_name": user.display_name or user.handle or "",
        "avatar_url": avatar_url(user),
    }


class PersonRefSerializer(serializers.Serializer):
    """Schema for :func:`person_ref`."""

    id = serializers.UUIDField()
    handle = serializers.CharField(allow_null=True)
    display_name = serializers.CharField()
    avatar_url = serializers.CharField(allow_null=True)

    def to_representation(self, instance: Any) -> Any:
        return instance if isinstance(instance, dict) else person_ref(instance)
