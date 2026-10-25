"""Per-request context propagated through ``contextvars``.

:class:`~university.core.middleware.RequestContextMiddleware` populates the
context; services, audit logging, events and log records read it without the
request object having to be threaded through every call.
"""

from __future__ import annotations

import contextvars
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class RequestContext:
    request_id: str | None = None
    ip_address: str | None = None
    user_agent: str = ""
    method: str = ""
    path: str = ""


_EMPTY = RequestContext()
_context: contextvars.ContextVar[RequestContext] = contextvars.ContextVar("university_request_context", default=_EMPTY)


def get_request_context() -> RequestContext:
    return _context.get()


def set_request_context(ctx: RequestContext) -> contextvars.Token[RequestContext]:
    return _context.set(ctx)


def reset_request_context(token: contextvars.Token[RequestContext]) -> None:
    _context.reset(token)


def update_request_context(**changes: object) -> None:
    _context.set(replace(_context.get(), **changes))  # type: ignore[arg-type]
