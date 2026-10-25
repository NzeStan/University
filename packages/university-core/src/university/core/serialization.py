"""Helpers for converting values into JSON-safe structures.

Events and task arguments cross process boundaries (brokers, queues), so
their payloads must be plain JSON. :func:`to_jsonable` converts common Python
and Django values; anything else raises ``TypeError`` early, in the caller.
"""

from __future__ import annotations

import datetime as dt
import decimal
import enum
import uuid
from collections.abc import Mapping
from typing import Any

from django.db import models


def to_jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (bool, int, float, str)):
        return value
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, (dt.datetime, dt.date, dt.time)):
        return value.isoformat()
    if isinstance(value, dt.timedelta):
        return value.total_seconds()
    if isinstance(value, decimal.Decimal):
        return str(value)
    if isinstance(value, enum.Enum):
        return to_jsonable(value.value)
    if isinstance(value, models.Model):
        return str(value.pk)
    if isinstance(value, Mapping):
        return {str(k): to_jsonable(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [to_jsonable(v) for v in value]
    raise TypeError(f"Value of type {type(value).__name__} is not JSON-serialisable.")
