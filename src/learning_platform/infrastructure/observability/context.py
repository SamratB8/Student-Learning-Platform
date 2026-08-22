"""Request correlation, carried without Flask.

A correlation identifier ties every log line and audit record produced while handling
one request. It lives in a :class:`~contextvars.ContextVar` rather than in a Flask
global so that background handlers, use cases, and tests can all set it, and so no
layer below ``web`` has to import Flask to read it.
"""

from __future__ import annotations

import uuid
from contextvars import ContextVar, Token

__all__ = [
    "bind_correlation_id",
    "clear_correlation_id",
    "current_correlation_id",
    "new_correlation_id",
]

_correlation_id: ContextVar[str | None] = ContextVar(
    "learning_platform_correlation_id", default=None
)


def new_correlation_id() -> str:
    """Generate a fresh correlation identifier."""
    return uuid.uuid7().hex


def bind_correlation_id(correlation_id: str) -> Token[str | None]:
    """Set the correlation identifier for the current context.

    Returns a token; pass it to :func:`clear_correlation_id` to restore the previous
    value. Restoring rather than clearing matters because a worker may process
    several units of work in one process.
    """
    return _correlation_id.set(correlation_id)


def clear_correlation_id(token: Token[str | None]) -> None:
    """Restore the correlation identifier that was set before ``token`` was issued."""
    _correlation_id.reset(token)


def current_correlation_id() -> str | None:
    """Return the correlation identifier for the current context, if any."""
    return _correlation_id.get()
