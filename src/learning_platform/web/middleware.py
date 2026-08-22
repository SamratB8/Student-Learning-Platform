"""Per-request correlation and access logging.

A correlation identifier is bound for the duration of each request, so every log line
and audit record produced while handling it can be tied together, and returned in a
response header so a user can quote it in a report.
"""

from __future__ import annotations

import time

from flask import Flask, Response, g, request

from learning_platform.infrastructure.observability.context import (
    bind_correlation_id,
    clear_correlation_id,
    new_correlation_id,
)
from learning_platform.infrastructure.observability.logging import get_logger

__all__ = ["CORRELATION_HEADER", "register_request_context"]

CORRELATION_HEADER = "X-Request-ID"

_logger = get_logger(__name__)


def register_request_context(app: Flask) -> None:
    """Bind a correlation identifier and log request completion."""

    @app.before_request
    def _begin_request() -> None:
        # An inbound header is not trusted as an identifier: it is client-controlled
        # and could be used to poison or forge log correlation. A fresh value is
        # always generated.
        correlation_id = new_correlation_id()
        g.correlation_id = correlation_id
        g.correlation_token = bind_correlation_id(correlation_id)
        g.request_started_at = time.perf_counter()

    @app.after_request
    def _log_request(response: Response) -> Response:
        correlation_id = g.get("correlation_id")
        if correlation_id is not None:
            response.headers.setdefault(CORRELATION_HEADER, correlation_id)

        started_at = g.get("request_started_at")
        duration_ms = (
            round((time.perf_counter() - started_at) * 1000, 2) if started_at is not None else None
        )

        _logger.info(
            "http.request",
            method=request.method,
            # url_rule is the matched route pattern, not the raw path, so identifiers
            # and query strings never reach the log.
            route=str(request.url_rule) if request.url_rule else "unmatched",
            status=response.status_code,
            duration_ms=duration_ms,
        )
        return response

    @app.teardown_request
    def _end_request(_exc: BaseException | None) -> None:
        token = g.pop("correlation_token", None)
        if token is not None:
            clear_correlation_id(token)
