"""Serializer base classes enforcing University conventions.

:class:`StrictModelSerializer` refuses ``fields = "__all__"`` and ``exclude``
at class-definition time. Writable fields must be listed explicitly, so a
model gaining a new column (``is_staff``, ``status`` …) can never become
client-writable by accident (mass-assignment protection).
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ImproperlyConfigured
from rest_framework import serializers


class StrictModelSerializerMetaclass(serializers.SerializerMetaclass):
    def __new__(mcs, name: str, bases: tuple[type, ...], attrs: dict[str, Any]) -> Any:
        cls = super().__new__(mcs, name, bases, attrs)
        meta = attrs.get("Meta")
        if meta is not None:
            if getattr(meta, "fields", None) == serializers.ALL_FIELDS:
                raise ImproperlyConfigured(f"{name}: fields = '__all__' is forbidden; list fields explicitly.")
            if getattr(meta, "exclude", None):
                raise ImproperlyConfigured(f"{name}: Meta.exclude is forbidden; list fields explicitly.")
        return cls


class StrictModelSerializer(serializers.ModelSerializer, metaclass=StrictModelSerializerMetaclass):
    """ModelSerializer with explicit-fields enforcement."""


class EmptySerializer(serializers.Serializer):
    """For endpoints without a request body (documentation only)."""


class DetailSerializer(serializers.Serializer):
    detail = serializers.CharField()


class ChallengeSerializer(serializers.Serializer):
    """A one-time-code challenge awaiting completion."""

    challenge_id = serializers.UUIDField()
    destination = serializers.CharField(required=False)
    channel = serializers.CharField(required=False)


class CountSerializer(serializers.Serializer):
    revoked = serializers.IntegerField()
