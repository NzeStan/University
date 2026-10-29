"""drf-spectacular integration. Referenced by dotted path from ``rest_framework_settings()``.

Kept out of ``schema.py`` because importing drf-spectacular's AutoSchema reads DRF settings, which
must not happen while Django settings are still loading.
"""

from __future__ import annotations

from drf_spectacular.openapi import AutoSchema as _AutoSchema

from university.core.api.schema import _is_paginated


class UniversityAutoSchema(_AutoSchema):
    """drf-spectacular's AutoSchema, aware of :func:`paginated` responses.

    A GET answering with a page object is still a *list* operation: it keeps the ``…_list``
    operation id instead of colliding with the detail endpoint's ``…_retrieve``.
    """

    def get_operation_id(self) -> str:
        operation_id = super().get_operation_id()
        if self.method == "GET" and _is_paginated(self.get_response_serializers()):
            if operation_id.endswith("_retrieve"):
                return operation_id.removesuffix("_retrieve") + "_list"
            if operation_id.startswith("retrieve_"):
                return "list_" + operation_id.removeprefix("retrieve_")
        return operation_id

    def _get_request_body(self, direction: str = "request"):  # type: ignore[no-untyped-def]
        # drf-spectacular documents bodies only for PUT/PATCH/POST. Some DELETEs need one (deleting
        # your account asks for your password): views opt in with ``documented_delete_body = True``.
        if self.method == "DELETE" and getattr(self.view, "documented_delete_body", False):
            self.method = "POST"
            try:
                return super()._get_request_body(direction)
            finally:
                self.method = "DELETE"
        return super()._get_request_body(direction)
