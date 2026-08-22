"""Response security headers.

ADR 0002 puts the application behind a hosting edge rather than a self-managed
reverse proxy. Headers are therefore set by the application, so they hold regardless
of what any edge is or is not configured to add.

The policy is intentionally strict now, while there is no UI to break. Loosening it
later for a specific surface is a deliberate, reviewable act; tightening it after
pages depend on inline script is not.
"""

from __future__ import annotations

from flask import Flask, Response

from learning_platform.infrastructure.config.settings import Settings

__all__ = ["register_security_headers"]

# One year, matching the usual preload requirement.
_HSTS_MAX_AGE = 31_536_000

_CONTENT_SECURITY_POLICY = "; ".join(
    [
        "default-src 'self'",
        # No inline or remote script. Frontend code is bundled and served from this
        # origin, so a CDN allowance is never needed.
        "script-src 'self'",
        "style-src 'self'",
        "img-src 'self' data:",
        "font-src 'self'",
        # Provider endpoints are added here explicitly when an integration needs one.
        "connect-src 'self'",
        "object-src 'none'",
        "base-uri 'none'",
        "frame-ancestors 'none'",
        "form-action 'self'",
    ]
)


def register_security_headers(app: Flask, settings: Settings) -> None:
    """Attach security headers to every response."""

    @app.after_request
    def _apply_security_headers(response: Response) -> Response:
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Content-Security-Policy", _CONTENT_SECURITY_POLICY)
        # Deny powerful features by default; a surface that needs one opts in.
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        # Cross-origin isolation defaults, so an embedded document or a popup cannot
        # reach into this origin.
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Cross-Origin-Resource-Policy", "same-origin")

        if settings.app_env.is_deployed:
            # Only sent when TLS is certain. Sending HSTS from a plain-http
            # development server would make localhost unreachable over http.
            response.headers.setdefault(
                "Strict-Transport-Security",
                f"max-age={_HSTS_MAX_AGE}; includeSubDomains",
            )
        return response
