"""Flask application factory.

There is no module-level ``app``. A factory is what makes it possible to build an
application per test with its own configuration, to build one inside a background
handler, and to satisfy ADR 0002's requirement that nothing be constructed at import
time and no state survive between requests.

Composition happens here and nowhere else: settings are loaded, adapters are built,
and they are attached to the application. Layers below ``web`` receive what they need
as arguments.
"""

from __future__ import annotations

from typing import Any

from flask import Flask

from learning_platform.infrastructure.config.settings import Settings, load_settings
from learning_platform.infrastructure.observability.logging import (
    configure_logging,
    get_logger,
)
from learning_platform.web.blueprints.health import health_blueprint
from learning_platform.web.errors import register_error_handlers
from learning_platform.web.extensions import EXTENSION_KEY, PlatformExtensions
from learning_platform.web.middleware import register_request_context
from learning_platform.web.security import register_security_headers

__all__ = ["create_app"]

# 25 MB. A ceiling exists from the first day so no surface is ever written assuming
# unbounded request bodies. Upload limits per resource type are set separately when
# uploads are implemented.
_MAX_CONTENT_LENGTH = 25 * 1024 * 1024

_logger = get_logger(__name__)


def create_app(settings: Settings | None = None, **overrides: Any) -> Flask:
    """Build a configured Flask application.

    Args:
        settings: pre-built settings, mainly for tests. When omitted, configuration
            is read from the environment and ``.env``.
        **overrides: settings overrides, applied only when ``settings`` is omitted.

    Raises:
        ConfigurationError: if the environment is missing or invalid. Startup fails
            rather than serving requests with unsafe defaults.
    """
    resolved = settings if settings is not None else load_settings(**overrides)

    configure_logging(resolved)

    app = Flask(__name__)
    _configure_flask(app, resolved)

    extensions = PlatformExtensions(resolved)
    app.extensions[EXTENSION_KEY] = extensions

    register_request_context(app)
    register_security_headers(app, resolved)
    register_error_handlers(app, resolved)

    app.register_blueprint(health_blueprint)

    # Non-secret facts only. Settings.safe_summary never returns a secret value.
    _logger.info("application.started", **resolved.safe_summary())

    return app


def _configure_flask(app: Flask, settings: Settings) -> None:
    """Apply Flask configuration derived from validated settings."""
    app.config.update(
        SECRET_KEY=settings.resolved_secret_key(),
        # Never enabled from configuration. The interactive debugger executes
        # arbitrary code and must not be reachable through an environment variable.
        DEBUG=False,
        TESTING=settings.testing,
        MAX_CONTENT_LENGTH=_MAX_CONTENT_LENGTH,
        # Session cookie hardening. Secure is off only where there is no TLS to
        # depend on, which is local development and tests.
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_COOKIE_SECURE=settings.app_env.is_deployed,
        SESSION_COOKIE_NAME="__Host-session" if settings.app_env.is_deployed else "session",
        PERMANENT_SESSION_LIFETIME=60 * 60 * 12,
        PREFERRED_URL_SCHEME="https" if settings.app_env.is_deployed else "http",
        # Fail loudly on a template that references an undefined name, rather than
        # rendering a blank where a value was expected.
        EXPLAIN_TEMPLATE_LOADING=False,
        JSON_SORT_KEYS=False,
        # Trailing-slash redirects turn a POST into a GET and silently drop the body.
        STRICT_SLASHES=False,
    )
    app.url_map.strict_slashes = False
