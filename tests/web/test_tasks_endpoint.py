"""The drain endpoint, which is the only externally reachable part of ADR 0004.

The happy path needs a database and lives in the integration tests. What is pinned
here is everything that must be refused, plus the structural claim the design rests
on: the endpoint reads nothing from the request except the ``Authorization`` header,
so "make it run an arbitrary task" is not a request that can be expressed.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import SecretStr

from learning_platform.infrastructure.config.settings import AppEnvironment, Settings
from learning_platform.web import create_app
from learning_platform.web.extensions import get_extensions

SECRET = "a-drain-secret-of-sufficient-length"
DRAIN = "/internal/tasks/drain"


@pytest.fixture
def secured_app() -> Iterator[Flask]:
    """An application with a drain secret but no database."""
    settings = Settings(
        app_env=AppEnvironment.TEST,
        deployment_key="test",
        database_url=SecretStr(""),
        task_runner_secret=SecretStr(SECRET),
    )
    application = create_app(settings)
    yield application
    get_extensions(application).shutdown()


@pytest.fixture
def secured_client(secured_app: Flask) -> FlaskClient:
    return secured_app.test_client()


def _authorized() -> dict[str, str]:
    return {"Authorization": f"Bearer {SECRET}"}


class TestAuthentication:
    def test_no_header_is_denied(self, secured_client: FlaskClient) -> None:
        response = secured_client.post(DRAIN)
        assert response.status_code == 401

    def test_a_wrong_secret_is_denied(self, secured_client: FlaskClient) -> None:
        response = secured_client.post(DRAIN, headers={"Authorization": "Bearer wrong"})
        assert response.status_code == 401

    def test_a_secret_that_is_a_prefix_is_denied(self, secured_client: FlaskClient) -> None:
        response = secured_client.post(DRAIN, headers={"Authorization": f"Bearer {SECRET[:-1]}"})
        assert response.status_code == 401

    @pytest.mark.parametrize(
        "header",
        [
            "",
            "Basic dXNlcjpwYXNz",
            "Token a-drain-secret-of-sufficient-length",
            "a-drain-secret-of-sufficient-length",
            "bearer a-drain-secret-of-sufficient-length",
        ],
    )
    def test_a_malformed_authorization_header_is_denied(
        self, secured_client: FlaskClient, header: str
    ) -> None:
        """Including the correct secret under the wrong scheme, and the wrong case."""
        response = secured_client.post(DRAIN, headers={"Authorization": header})
        assert response.status_code == 401

    def test_the_correct_secret_gets_past_authentication(self, secured_client: FlaskClient) -> None:
        """503 rather than 401: authenticated, but there is no database to drain."""
        response = secured_client.post(DRAIN, headers=_authorized())
        assert response.status_code == 503

    def test_a_denial_reveals_nothing(self, secured_client: FlaskClient) -> None:
        body = secured_client.post(DRAIN).get_json()
        assert body == {"status": "denied"}


class TestUnconfiguredDeploymentDeniesEverything:
    def test_no_configured_secret_denies_every_request(self, client: FlaskClient) -> None:
        """Fail closed. An absent secret must never mean 'no authentication needed'."""
        assert client.post(DRAIN).status_code == 401
        assert client.post(DRAIN, headers={"Authorization": "Bearer "}).status_code == 401
        assert client.post(DRAIN, headers={"Authorization": "Bearer x"}).status_code == 401

    def test_an_empty_bearer_does_not_match_an_empty_secret(self, client: FlaskClient) -> None:
        """The comparison must not succeed by both sides being blank."""
        response = client.post(DRAIN, headers={"Authorization": "Bearer "})
        assert response.status_code == 401

    def test_the_denial_is_indistinguishable_from_a_wrong_secret(
        self, client: FlaskClient, secured_client: FlaskClient
    ) -> None:
        """Probing must not reveal whether background processing is configured."""
        unconfigured = client.post(DRAIN, headers={"Authorization": "Bearer guess"})
        misconfigured = secured_client.post(DRAIN, headers={"Authorization": "Bearer guess"})

        assert unconfigured.status_code == misconfigured.status_code
        assert unconfigured.get_json() == misconfigured.get_json()


class TestTheEndpointTakesNoInput:
    """The structural claim: nothing but the Authorization header is read."""

    def test_a_task_type_in_the_body_is_ignored(self, secured_client: FlaskClient) -> None:
        response = secured_client.post(
            DRAIN,
            headers=_authorized(),
            json={"task_type": "os.system", "payload": {"cmd": "rm -rf /"}},
        )
        # Reaches the database check unchanged: the body did not select anything.
        assert response.status_code == 503

    def test_query_parameters_are_ignored(self, secured_client: FlaskClient) -> None:
        response = secured_client.post(
            f"{DRAIN}?task_type=demo.run&limit=100000", headers=_authorized()
        )
        assert response.status_code == 503

    def test_an_unauthenticated_request_with_a_payload_is_still_denied(
        self, secured_client: FlaskClient
    ) -> None:
        response = secured_client.post(DRAIN, json={"task_type": "demo.run"})
        assert response.status_code == 401

    def test_the_route_reads_only_the_authorization_header(self) -> None:
        """Pins the property in source, so a later edit that starts parsing a body
        has to change this test deliberately."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "learning_platform"
            / "web"
            / "blueprints"
            / "tasks.py"
        ).read_text(encoding="utf-8-sig")

        for forbidden in ("request.get_json", "request.form", "request.args", "request.data"):
            assert forbidden not in source, f"the drain endpoint must not read {forbidden}"
        assert 'request.headers.get("Authorization"' in source


class TestMethods:
    def test_get_is_accepted_because_the_scheduler_issues_one(
        self, secured_client: FlaskClient
    ) -> None:
        """Vercel Cron makes an HTTP GET. Refusing it would make the design undeployable."""
        assert secured_client.get(DRAIN, headers=_authorized()).status_code == 503

    def test_post_is_accepted(self, secured_client: FlaskClient) -> None:
        assert secured_client.post(DRAIN, headers=_authorized()).status_code == 503

    @pytest.mark.parametrize("method", ["put", "delete", "patch"])
    def test_other_methods_are_refused(self, secured_client: FlaskClient, method: str) -> None:
        response = getattr(secured_client, method)(DRAIN, headers=_authorized())
        assert response.status_code == 405

    def test_an_unauthenticated_get_is_denied(self, secured_client: FlaskClient) -> None:
        assert secured_client.get(DRAIN).status_code == 401


class TestConfigurationReporting:
    def test_the_startup_summary_reports_whether_drains_are_possible(self) -> None:
        settings = Settings(
            app_env=AppEnvironment.TEST,
            deployment_key="test",
            task_runner_secret=SecretStr(SECRET),
        )
        assert settings.safe_summary()["task_invocation"] == "configured"

    def test_an_unconfigured_runner_is_reported_as_such(self, test_settings: Settings) -> None:
        assert test_settings.safe_summary()["task_invocation"] == "unconfigured"

    def test_the_summary_never_contains_the_secret(self) -> None:
        settings = Settings(
            app_env=AppEnvironment.TEST,
            deployment_key="test",
            task_runner_secret=SecretStr(SECRET),
        )
        assert SECRET not in repr(settings.safe_summary())
        assert SECRET not in repr(settings)
