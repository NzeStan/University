from __future__ import annotations

from typing import Any

from university.core.conf import ModuleSettings

DEFAULTS: dict[str, Any] = {
    "ENABLED": True,
    "MAX_ITEMS_PER_USER": 100,
}

__module___settings = ModuleSettings("__MODULE__", DEFAULTS)
