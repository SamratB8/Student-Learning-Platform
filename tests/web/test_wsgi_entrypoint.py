"""The hosting entry point must expose the real application.

These tests contact nothing. They check the contract Vercel's Python runtime relies
on, so a rename or an accidental second Flask application is caught locally rather
than by a failed deployment.

``wsgi`` is imported inside each test rather than at module scope because importing it
runs ``create_app()``, which reads the environment. Importing at module scope would
run that during collection, before the fixture that isolates the environment.
"""

from __future__ import annotations

import importlib
import sys
import tomllib
from collections.abc import Iterator
from pathlib import Path
from types import ModuleType

import pytest
from flask import Flask

from learning_platform.web.extensions import EXTENSION_KEY, get_extensions

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def wsgi_module(monkeypatch: pytest.MonkeyPatch) -> Iterator[ModuleType]:
    """Import ``wsgi`` freshly with a valid deployed-style configuration.

    The module is removed from ``sys.modules`` afterwards so it is rebuilt per test
    and does not leak an application into other tests.
    """
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DEPLOYMENT_KEY", "test")
    monkeypatch.setenv("APP_BASE_URL", "https://example.test")
    monkeypatch.setenv("SECRET_KEY", "t" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.invalid:5432/db")

    sys.modules.pop("wsgi", None)
    module = importlib.import_module("wsgi")
    yield module
    get_extensions(module.app).shutdown()
    sys.modules.pop("wsgi", None)


class TestEntrypointContract:
    """What Vercel's Python runtime requires of this module."""

    def test_the_module_exposes_a_name_called_app(self, wsgi_module: ModuleType) -> None:
        assert hasattr(wsgi_module, "app")

    def test_app_is_a_flask_application(self, wsgi_module: ModuleType) -> None:
        assert isinstance(wsgi_module.app, Flask)

    def test_app_is_callable_as_a_wsgi_application(self, wsgi_module: ModuleType) -> None:
        """Vercel invokes it through the WSGI protocol, not through Flask's API."""
        assert callable(wsgi_module.app.wsgi_app)

    def test_the_application_was_built_by_the_factory(self, wsgi_module: ModuleType) -> None:
        """Guards against a second Flask application being constructed here."""
        assert EXTENSION_KEY in wsgi_module.app.extensions

    def test_the_declared_entrypoint_matches_this_module(self) -> None:
        """pyproject.toml and the actual file must not drift apart."""
        with (REPOSITORY_ROOT / "pyproject.toml").open("rb") as handle:
            configured = tomllib.load(handle)["tool"]["vercel"]["entrypoint"]

        module_path, _, variable = configured.partition(":")
        assert variable == "app"
        assert (REPOSITORY_ROOT / f"{module_path.replace('.', '/')}.py").is_file()


class TestEntrypointStaysThin:
    """The adapter is a hosting seam, not a place for application logic."""

    def test_it_registers_no_routes_of_its_own(self, wsgi_module: ModuleType) -> None:
        """The entrypoint exposes exactly what ``create_app`` builds, and nothing more.

        Compared against a freshly built application rather than against a fixed
        count, so adding a blueprint the ordinary way does not fail this test while
        a route defined in the adapter still does.
        """
        from pydantic import SecretStr

        from learning_platform.infrastructure.config.settings import AppEnvironment, Settings
        from learning_platform.web import create_app
        from learning_platform.web.extensions import get_extensions

        reference = create_app(
            Settings(
                app_env=AppEnvironment.TEST,
                deployment_key="test",
                database_url=SecretStr(""),
            )
        )
        try:
            expected = {rule.rule for rule in reference.url_map.iter_rules()}
        finally:
            get_extensions(reference).shutdown()

        assert {rule.rule for rule in wsgi_module.app.url_map.iter_rules()} == expected
        assert "/healthz" in expected

    def test_it_does_not_reconfigure_the_application(self, wsgi_module: ModuleType) -> None:
        """Settings come from create_app, so deployed hardening must already hold."""
        assert wsgi_module.app.config["DEBUG"] is False
        assert wsgi_module.app.config["SESSION_COOKIE_SECURE"] is True


class TestDeployedBehaviour:
    """Behaviour a Vercel invocation depends on, exercised through the test client."""

    def test_liveness_answers_without_a_reachable_database(self, wsgi_module: ModuleType) -> None:
        """A missing database must not stop the process reporting itself alive."""
        response = wsgi_module.app.test_client().get("/healthz")
        assert response.status_code == 200
        assert response.get_json() == {"status": "ok"}

    def test_missing_configuration_prevents_the_module_importing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A deployment that cannot be configured safely must fail to boot."""
        from learning_platform.domain.errors import ConfigurationError

        monkeypatch.setenv("APP_ENV", "staging")
        monkeypatch.delenv("SECRET_KEY", raising=False)
        monkeypatch.delenv("DATABASE_URL", raising=False)

        sys.modules.pop("wsgi", None)
        try:
            with pytest.raises(ConfigurationError):
                importlib.import_module("wsgi")
        finally:
            sys.modules.pop("wsgi", None)
