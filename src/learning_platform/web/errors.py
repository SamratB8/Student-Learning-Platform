"""Error handling.

Two rules shape this module:

* A client never learns more than its own request justifies. Unexpected exceptions
  produce a generic message and a correlation identifier; the detail goes to the log.
* :class:`~learning_platform.domain.errors.NotFound` and
  :class:`~learning_platform.domain.errors.AuthorizationDenied` both answer 404, so
  probing identifiers cannot distinguish "exists but forbidden" from "absent".
"""

from __future__ import annotations

from typing import Any

from flask import Flask, g, jsonify
from flask.wrappers import Response
from werkzeug.exceptions import HTTPException

from learning_platform.domain.errors import (
    AuthorizationDenied,
    DomainError,
    InvariantViolation,
    NotFound,
    ValidationFailed,
)
from learning_platform.infrastructure.config.settings import Settings
from learning_platform.infrastructure.observability.logging import get_logger

__all__ = ["register_error_handlers"]

_logger = get_logger(__name__)

_GENERIC_MESSAGE = "An unexpected error occurred."


def _error_response(code: str, message: str, status: int) -> tuple[Response, int]:
    body: dict[str, Any] = {"error": {"code": code, "message": message}}
    correlation_id = g.get("correlation_id")
    if correlation_id is not None:
        body["error"]["correlation_id"] = correlation_id
    return jsonify(body), status


def register_error_handlers(app: Flask, settings: Settings) -> None:
    """Register handlers that never leak internal detail."""

    @app.errorhandler(ValidationFailed)
    def _handle_validation(exc: ValidationFailed) -> tuple[Response, int]:
        return _error_response(exc.code, exc.message, 400)

    @app.errorhandler(AuthorizationDenied)
    def _handle_denied(exc: AuthorizationDenied) -> tuple[Response, int]:
        # Answered as 404 on purpose. A 403 confirms the target exists.
        _logger.warning("authorization.denied", reason=exc.code)
        return _error_response(NotFound.code, NotFound.message, 404)

    @app.errorhandler(NotFound)
    def _handle_not_found(exc: NotFound) -> tuple[Response, int]:
        return _error_response(exc.code, exc.message, 404)

    @app.errorhandler(InvariantViolation)
    def _handle_invariant(exc: InvariantViolation) -> tuple[Response, int]:
        # A broken invariant is a defect. It is logged as one and reported generically.
        _logger.error("domain.invariant_violation", detail=str(exc))
        return _error_response("internal_error", _GENERIC_MESSAGE, 500)

    @app.errorhandler(DomainError)
    def _handle_domain_error(exc: DomainError) -> tuple[Response, int]:
        return _error_response(exc.code, exc.message, 400)

    @app.errorhandler(HTTPException)
    def _handle_http_exception(exc: HTTPException) -> tuple[Response, int]:
        # Werkzeug descriptions are written for end users and contain no internals.
        return _error_response(
            code=exc.name.lower().replace(" ", "_"),
            message=exc.description or exc.name,
            status=exc.code or 500,
        )

    @app.errorhandler(Exception)
    def _handle_unexpected(exc: Exception) -> tuple[Response, int]:
        _logger.exception("http.unhandled_exception", exception_type=type(exc).__name__)
        if settings.debug:
            # Development only, and only the exception's own text. Even here the
            # traceback stays in the log rather than going to the client.
            return _error_response("internal_error", f"{type(exc).__name__}: {exc}", 500)
        return _error_response("internal_error", _GENERIC_MESSAGE, 500)
