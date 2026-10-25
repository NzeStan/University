"""View helpers shared by University modules."""

from __future__ import annotations

from typing import Any

from django.http import HttpRequest, JsonResponse

from university.core.api.exceptions import error_body


def json_page_not_found(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    """``handler404`` that answers in the standard error envelope."""
    return JsonResponse(error_body("not_found", "Not found."), status=404)


def json_server_error(request: HttpRequest, *args: Any, **kwargs: Any) -> JsonResponse:
    """``handler500`` that answers in the standard error envelope."""
    return JsonResponse(error_body("server_error", "An unexpected error occurred."), status=500)


def json_permission_denied(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return JsonResponse(error_body("permission_denied", "Permission denied."), status=403)


def json_bad_request(request: HttpRequest, exception: Exception | None = None) -> JsonResponse:
    return JsonResponse(error_body("bad_request", "Bad request."), status=400)
