"""End-to-end: the fail-closed rule as it is actually reached at startup.

``test_hosted_environment.py`` pins the rule itself against a synthetic mapping.
These tests drive the real entry points, ``load_settings`` and
``load_hosted_settings``, through ``os.environ``, so they cover the wiring as well as
the decision.
"""

from __future__ import annotations

import pytest

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.settings import (
    AppEnvironment,
    load_hosted_settings,
    load_settings,
)


def _deployed_configuration(monkeypatch: pytest.MonkeyPatch) -> None:
    """Everything a deployed environment requires, except APP_ENV."""
    monkeypatch.setenv("DEPLOYMENT_KEY", "test")
    monkeypatch.setenv("APP_BASE_URL", "https://example.test")
    monkeypatch.setenv("SECRET_KEY", "s" * 48)
    monkeypatch.setenv("DATABASE_URL", "postgresql://u:p@db.invalid:5432/db")


class TestLocalStartupIsUnchanged:
    def test_a_bare_local_environment_still_starts_as_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        settings = load_settings()
        assert settings.app_env is AppEnvironment.DEVELOPMENT
        assert settings.debug is True

    def test_an_explicit_override_is_respected(self) -> None:
        """Calling code that states the value has no fallback to remove."""
        assert load_settings(app_env=AppEnvironment.TEST).app_env is AppEnvironment.TEST


class TestVercelProductionStartup:
    """The incident, reproduced through the real loader."""

    def test_missing_app_env_does_not_start_as_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("VERCEL", "1")
        monkeypatch.setenv("VERCEL_ENV", "production")

        settings = load_settings()

        assert settings.app_env is AppEnvironment.PRODUCTION
        assert settings.debug is False
        assert settings.app_env.is_deployed is True

    def test_missing_required_configuration_now_fails_instead_of_degrading(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Previously this booted quietly as development. Now it refuses.

        This is the whole point of the change: with no SECRET_KEY and no DATABASE_URL,
        the old behaviour was a running public site in development mode.
        """
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("VERCEL", "1")
        monkeypatch.setenv("VERCEL_ENV", "production")

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        message = str(error.value)
        assert "SECRET_KEY" in message
        assert "DATABASE_URL" in message

    def test_the_resulting_application_has_deployed_hardening(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("VERCEL_ENV", "production")

        from learning_platform.web import create_app
        from learning_platform.web.extensions import get_extensions

        app = create_app(load_settings())
        try:
            assert app.config["SESSION_COOKIE_SECURE"] is True
            assert app.config["SESSION_COOKIE_NAME"].startswith("__Host-")
            assert app.config["DEBUG"] is False
        finally:
            get_extensions(app).shutdown()


class TestVercelPreviewStartup:
    def test_missing_app_env_resolves_to_staging(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("VERCEL", "1")
        monkeypatch.setenv("VERCEL_ENV", "preview")

        settings = load_settings()

        assert settings.app_env is AppEnvironment.STAGING
        assert settings.debug is False

    def test_a_preview_never_becomes_local_development(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.delenv("DATABASE_URL", raising=False)
        monkeypatch.setenv("VERCEL_ENV", "preview")

        with pytest.raises(ConfigurationError):
            load_settings()


class TestAmbiguousHostedStartup:
    def test_a_hosted_process_with_no_reported_environment_refuses_to_start(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("VERCEL_URL", "example.vercel.app")

        with pytest.raises(ConfigurationError, match="could not"):
            load_settings()

    def test_an_explicit_app_env_resolves_it(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("VERCEL_URL", "example.vercel.app")
        monkeypatch.setenv("APP_ENV", "staging")

        assert load_settings().app_env is AppEnvironment.STAGING


class TestHostedLoaderAssertsWithoutMarkers:
    """What the hosting entry point uses, with system variables switched off."""

    def test_it_refuses_to_default_to_development(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _deployed_configuration(monkeypatch)

        with pytest.raises(ConfigurationError, match="could not"):
            load_hosted_settings()

    def test_it_accepts_an_explicit_deployed_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("APP_ENV", "staging")

        assert load_hosted_settings().app_env is AppEnvironment.STAGING

    def test_it_refuses_an_explicit_development_environment(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _deployed_configuration(monkeypatch)
        monkeypatch.setenv("APP_ENV", "development")

        with pytest.raises(ConfigurationError, match="developer"):
            load_hosted_settings()


class TestFailureMessagesStillLeakNothing:
    """The hardening must not reintroduce the disclosure fixed earlier."""

    CANARY = "pw0canary"

    def test_an_ambiguous_hosted_failure_does_not_echo_the_database_password(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        import traceback

        monkeypatch.setenv("DEPLOYMENT_KEY", "test")
        monkeypatch.setenv("APP_BASE_URL", "https://example.test")
        monkeypatch.setenv("SECRET_KEY", "s" * 48)
        monkeypatch.setenv("DATABASE_URL", f"postgresql://u:{self.CANARY}@db.invalid/db")
        monkeypatch.setenv("VERCEL_URL", "example.vercel.app")

        try:
            load_settings()
        except ConfigurationError as exc:
            rendered = "".join(traceback.format_exception(type(exc), exc, exc.__traceback__))
        else:  # pragma: no cover - the configuration is ambiguous by construction
            raise AssertionError("startup was expected to be refused")

        assert self.CANARY not in rendered

    def test_a_rejected_app_env_value_is_not_echoed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("APP_ENV", "prodcution")

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        assert "prodcution" not in str(error.value)
        assert "APP_ENV" in str(error.value)
