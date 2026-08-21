"""Application factory, health endpoints, security headers, and error behavior."""

from __future__ import annotations

from typing import NoReturn

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import SecretStr

from learning_platform.domain.errors import (
    AuthorizationDenied,
    ConfigurationError,
    NotFound,
    ValidationFailed,
)
from learning_platform.infrastructure.config.settings import AppEnvironment, Settings
from learning_platform.web import create_app
from learning_platform.web.extensions import EXTENSION_KEY, get_extensions
from learning_platform.web.middleware import CORRELATION_HEADER


class TestFactory:
    def test_an_application_is_created(self, app: Flask) -> None:
        assert isinstance(app, Flask)

    def test_two_applications_are_independent(self, test_settings: Settings) -> None:
        """No module-level app, so tests and background handlers can each build one."""
        first = create_app(test_settings)
        second = create_app(test_settings)
        try:
            assert first is not second
            assert first.extensions[EXTENSION_KEY] is not second.extensions[EXTENSION_KEY]
        finally:
            get_extensions(first).shutdown()
            get_extensions(second).shutdown()

    def test_debug_is_never_enabled_by_configuration(
        self, monkeypatch: pytest.MonkeyPatch, test_settings: Settings
    ) -> None:
        """A stray DEBUG variable must not expose the interactive debugger."""
        monkeypatch.setenv("DEBUG", "1")
        monkeypatch.setenv("FLASK_DEBUG", "1")
        app = create_app(test_settings)
        try:
            assert app.config["DEBUG"] is False
        finally:
            get_extensions(app).shutdown()

    def test_a_request_body_ceiling_is_set(self, app: Flask) -> None:
        assert app.config["MAX_CONTENT_LENGTH"] > 0

    def test_invalid_configuration_prevents_startup(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A misconfigured deployment fails fast rather than serving requests."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "too-short")
        with pytest.raises(ConfigurationError):
            create_app()

    def test_no_database_configured_is_a_valid_state(self, app: Flask) -> None:
        assert get_extensions(app).database_available is False

    def test_asking_for_an_absent_database_fails_clearly(self, app: Flask) -> None:
        with pytest.raises(RuntimeError, match="no database"):
            _ = get_extensions(app).engine


class TestSessionCookies:
    def _app(self, environment: AppEnvironment) -> Flask:
        settings = Settings(
            app_env=environment,
            deployment_key="test",
            secret_key=SecretStr("x" * 40),
            database_url=SecretStr("postgresql://u:p@localhost:5432/db"),
            app_base_url="https://example.test",
        )
        return create_app(settings)

    def test_deployed_environments_require_secure_cookies(self) -> None:
        app = self._app(AppEnvironment.PRODUCTION)
        try:
            assert app.config["SESSION_COOKIE_SECURE"] is True
            assert app.config["SESSION_COOKIE_HTTPONLY"] is True
            assert app.config["SESSION_COOKIE_SAMESITE"] == "Lax"
            assert app.config["SESSION_COOKIE_NAME"].startswith("__Host-")
        finally:
            get_extensions(app).shutdown()

    def test_local_development_does_not_require_tls(self, app: Flask) -> None:
        assert app.config["SESSION_COOKIE_SECURE"] is False
        assert app.config["SESSION_COOKIE_HTTPONLY"] is True


class TestHealthEndpoints:
    def test_liveness_reports_ok(self, client: FlaskClient) -> None:
        response = client.get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_liveness_does_not_touch_the_database(self, client: FlaskClient) -> None:
        """A database outage must not cause a restart loop."""
        assert client.get("/healthz").status_code == 200

    def test_readiness_reports_an_unconfigured_database_distinctly(
        self, client: FlaskClient
    ) -> None:
        response = client.get("/readyz")
        assert response.status_code == 200
        assert response.get_json()["checks"]["database"] == "not_configured"

    def test_readiness_answers_503_when_the_database_is_unreachable(self) -> None:
        """A configured but unreachable dependency must stop traffic being routed here.

        Port 1 on loopback has no listener. Windows does not refuse it promptly, so
        the connect timeout is what bounds this; it is set to the two-second floor
        libpq permits.
        """
        settings = Settings(
            app_env=AppEnvironment.TEST,
            deployment_key="test",
            database_url=SecretStr("postgresql://u:p@127.0.0.1:1/db"),
            database_connect_timeout_seconds=2,
        )
        app = create_app(settings)
        try:
            response = app.test_client().get("/readyz")
            assert response.status_code == 503
            assert response.get_json()["status"] == "not_ready"
            assert response.get_json()["checks"]["database"] == "unavailable"
        finally:
            get_extensions(app).shutdown()

    def test_liveness_stays_ok_when_the_database_is_unreachable(self) -> None:
        """Liveness must not depend on a dependency, or an outage causes a restart loop."""
        settings = Settings(
            app_env=AppEnvironment.TEST,
            deployment_key="test",
            database_url=SecretStr("postgresql://u:p@127.0.0.1:1/db"),
            database_connect_timeout_seconds=2,
        )
        app = create_app(settings)
        try:
            assert app.test_client().get("/healthz").status_code == 200
        finally:
            get_extensions(app).shutdown()

    def test_health_responses_disclose_nothing(self, client: FlaskClient) -> None:
        """Both endpoints are unauthenticated, so both stay uninformative."""
        body = str(client.get("/healthz").get_json()) + str(client.get("/readyz").get_json())
        for leak in ("version", "hostname", "postgres", "python", "flask", "traceback"):
            assert leak not in body.lower()


class TestSecurityHeaders:
    @pytest.mark.parametrize(
        ("header", "expected"),
        [
            ("X-Content-Type-Options", "nosniff"),
            ("X-Frame-Options", "DENY"),
            ("Referrer-Policy", "strict-origin-when-cross-origin"),
            ("Cross-Origin-Opener-Policy", "same-origin"),
        ],
    )
    def test_baseline_headers_are_present(
        self, client: FlaskClient, header: str, expected: str
    ) -> None:
        assert client.get("/healthz").headers[header] == expected

    def test_the_content_security_policy_forbids_inline_script(self, client: FlaskClient) -> None:
        policy = client.get("/healthz").headers["Content-Security-Policy"]
        assert "script-src 'self'" in policy
        assert "unsafe-inline" not in policy
        assert "frame-ancestors 'none'" in policy

    def test_hsts_is_absent_without_tls(self, client: FlaskClient) -> None:
        """Sending HSTS from a plain-http dev server would break localhost."""
        assert "Strict-Transport-Security" not in client.get("/healthz").headers

    def test_hsts_is_present_when_deployed(self) -> None:
        settings = Settings(
            app_env=AppEnvironment.PRODUCTION,
            deployment_key="test",
            secret_key=SecretStr("x" * 40),
            database_url=SecretStr("postgresql://u:p@localhost:5432/db"),
            app_base_url="https://example.test",
        )
        app = create_app(settings)
        try:
            response = app.test_client().get("/healthz")
            assert "max-age=" in response.headers["Strict-Transport-Security"]
        finally:
            get_extensions(app).shutdown()


class TestCorrelation:
    def test_every_response_carries_a_correlation_id(self, client: FlaskClient) -> None:
        assert client.get("/healthz").headers[CORRELATION_HEADER]

    def test_each_request_gets_a_distinct_id(self, client: FlaskClient) -> None:
        first = client.get("/healthz").headers[CORRELATION_HEADER]
        second = client.get("/healthz").headers[CORRELATION_HEADER]
        assert first != second

    def test_a_client_supplied_id_is_not_trusted(self, client: FlaskClient) -> None:
        """A client-controlled value could be used to forge or poison correlation."""
        response = client.get("/healthz", headers={CORRELATION_HEADER: "forged-by-client"})
        assert response.headers[CORRELATION_HEADER] != "forged-by-client"


class TestErrorHandling:
    def test_an_unknown_route_returns_a_structured_404(self, client: FlaskClient) -> None:
        response = client.get("/does-not-exist")
        assert response.status_code == 404
        assert response.get_json()["error"]["code"]

    def test_a_denial_is_indistinguishable_from_a_missing_record(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """Otherwise a 403 confirms that the target exists."""

        @app.get("/denied")
        def _denied() -> NoReturn:
            raise AuthorizationDenied

        @app.get("/absent")
        def _absent() -> NoReturn:
            raise NotFound

        denied_response = client.get("/denied")
        absent_response = client.get("/absent")
        assert denied_response.status_code == absent_response.status_code == 404

        denied = denied_response.get_json()["error"]
        absent = absent_response.get_json()["error"]

        # The correlation identifier legitimately differs per request; nothing else
        # may, or the response would distinguish the two cases.
        assert {key: value for key, value in denied.items() if key != "correlation_id"} == {
            key: value for key, value in absent.items() if key != "correlation_id"
        }

    def test_a_validation_failure_answers_400(self, app: Flask, client: FlaskClient) -> None:
        @app.get("/invalid")
        def _invalid() -> NoReturn:
            raise ValidationFailed("The branch is not recognised.")

        response = client.get("/invalid")
        assert response.status_code == 400
        assert response.get_json()["error"]["message"] == "The branch is not recognised."

    def test_an_unexpected_exception_does_not_leak_internals(
        self, app: Flask, client: FlaskClient
    ) -> None:
        @app.get("/boom")
        def _boom() -> NoReturn:
            raise RuntimeError("connection string postgresql://user:hunter2@db/app")

        response = client.get("/boom")

        assert response.status_code == 500
        body = response.get_data(as_text=True)
        assert "hunter2" not in body
        assert "Traceback" not in body
        assert response.get_json()["error"]["message"] == "An unexpected error occurred."

    def test_an_error_response_carries_the_correlation_id(
        self, app: Flask, client: FlaskClient
    ) -> None:
        """So a user can quote it in a report without being shown internals."""

        @app.get("/boom")
        def _boom() -> NoReturn:
            raise RuntimeError("failure")

        assert client.get("/boom").get_json()["error"]["correlation_id"]
