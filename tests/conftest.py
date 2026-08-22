"""Shared test fixtures.

Tests build their own settings explicitly rather than reading the developer's
environment. A test that passes only because of a local ``.env`` is not a test.
"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from flask import Flask
from flask.testing import FlaskClient
from pydantic import SecretStr

from learning_platform.infrastructure.config.hosting import VERCEL_MARKER_VARIABLES
from learning_platform.infrastructure.config.settings import AppEnvironment, Settings
from learning_platform.web import create_app
from learning_platform.web.extensions import get_extensions


@pytest.fixture(autouse=True)
def isolated_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove application environment variables for the duration of each test.

    Without this, a developer's ``.env`` or shell would silently change what the
    configuration tests are asserting, and results would differ between machines and
    CI. ``DATABASE_URL`` is deliberately not cleared here; integration tests need it,
    and they opt in explicitly.

    Vercel marker variables are cleared too. They decide whether the application
    considers itself hosted, so a shell that happens to define one would change what
    every configuration test is asserting.
    """
    for name in (
        "APP_ENV",
        "DEPLOYMENT_KEY",
        "APP_BASE_URL",
        "SECRET_KEY",
        "LOG_LEVEL",
        "LOG_FORMAT",
        *VERCEL_MARKER_VARIABLES,
    ):
        monkeypatch.delenv(name, raising=False)


@pytest.fixture
def test_settings() -> Settings:
    """Settings for a test application, with no database configured.

    ``database_url`` is set explicitly rather than left to default, because
    ``DATABASE_URL`` stays in the environment for integration tests and would
    otherwise be picked up here, making these tests pass or fail depending on
    whether the developer had started PostgreSQL.
    """
    return Settings(
        app_env=AppEnvironment.TEST,
        deployment_key="test",
        app_base_url="http://127.0.0.1:5000",
        database_url=SecretStr(""),
    )


@pytest.fixture
def app(test_settings: Settings) -> Iterator[Flask]:
    """A configured application, torn down cleanly."""
    application = create_app(test_settings)
    yield application
    get_extensions(application).shutdown()


@pytest.fixture
def client(app: Flask) -> FlaskClient:
    """A test client. No server process is started."""
    return app.test_client()


@pytest.fixture(scope="session")
def database_url() -> str:
    """The PostgreSQL URL for integration tests, or skip if none is configured.

    Skipping rather than falling back to SQLite is deliberate: ADR 0001 requires
    PostgreSQL-backed integration tests, and a SQLite substitute would quietly stop
    exercising JSONB, UUID, and timezone-aware timestamp behavior.
    """
    url = os.environ.get("DATABASE_URL", "").strip()
    if not url:
        pytest.skip(
            "DATABASE_URL is not set; start development PostgreSQL and set it to run "
            "integration tests"
        )
    return url
