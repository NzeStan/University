"""Pagination classes.

* :class:`CursorPagination` — for high-volume feeds and timelines. Stable
  under concurrent inserts and O(1) regardless of depth.
* :class:`PageNumberPagination` — for administrative and data-heavy lists
  where jumping to a page matters.

Page sizes come from ``UNIVERSITY["PAGINATION"]``.
"""

from __future__ import annotations

from typing import Any

from rest_framework import pagination

from university.core.conf import university_settings


class _SettingsPageSize:
    page_size_query_param = "page_size"

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.page_size = int(university_settings.get("PAGINATION.PAGE_SIZE", 20))
        self.max_page_size = int(university_settings.get("PAGINATION.MAX_PAGE_SIZE", 100))


class CursorPagination(_SettingsPageSize, pagination.CursorPagination):
    ordering = ("-created_at", "-id")


class PageNumberPagination(_SettingsPageSize, pagination.PageNumberPagination):
    pass
