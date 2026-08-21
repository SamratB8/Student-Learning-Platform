"""Configuration validation, including the cases that must fail startup."""

from __future__ import annotations

import pytest
from pydantic import SecretStr

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.settings import (
    AppEnvironment,
    LogFormat,
    Settings,
    load_settings,
)


class TestDefaults:
    def test_development_is_the_default_environment(self) -> None:
        settings = Settings()
        assert settings.app_env is AppEnvironment.DEVELOPMENT
        assert settings.debug is True

    def test_only_development_enables_debug(self) -> None:
        for environment in AppEnvironment:
            settings = Settings(
                app_env=environment,
                deployment_key="test",
                secret_key=SecretStr("x" * 40),
                database_url=SecretStr("postgresql://u:p@localhost:5432/db"),
                app_base_url="https://example.test",
            )
            assert settings.debug is (environment is AppEnvironment.DEVELOPMENT)

    def test_log_format_defaults_by_environment(self) -> None:
        local = Settings(app_env=AppEnvironment.TEST)
        assert local.effective_log_format is LogFormat.CONSOLE

        deployed = Settings(
            app_env=AppEnvironment.PRODUCTION,
            deployment_key="test",
            secret_key=SecretStr("x" * 40),
            database_url=SecretStr("postgresql://u:p@localhost:5432/db"),
            app_base_url="https://example.test",
        )
        assert deployed.effective_log_format is LogFormat.JSON


class TestDeployedEnvironmentRequirements:
    """Staging and production must not start with a weak or missing configuration."""

    def _deployed(self, **overrides: object) -> Settings:
        values: dict[str, object] = {
            "app_env": AppEnvironment.PRODUCTION,
            "deployment_key": "test",
            "secret_key": "x" * 40,
            "database_url": "postgresql://u:p@localhost:5432/db",
            "app_base_url": "https://example.test",
        }
        values.update(overrides)
        return Settings(**values)  # type: ignore[arg-type]

    def test_a_complete_configuration_is_accepted(self) -> None:
        assert self._deployed().app_env is AppEnvironment.PRODUCTION

    def test_missing_secret_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY"):
            self._deployed(secret_key=SecretStr(""))

    def test_placeholder_secret_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="placeholder"):
            self._deployed(secret_key=SecretStr("change-me"))

    def test_short_secret_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="at least"):
            self._deployed(secret_key=SecretStr("short"))

    def test_missing_database_url_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="DATABASE_URL"):
            self._deployed(database_url=SecretStr(""))

    def test_missing_deployment_key_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="DEPLOYMENT_KEY"):
            self._deployed(deployment_key="")

    def test_plain_http_base_url_is_rejected(self) -> None:
        with pytest.raises(ValueError, match="https"):
            self._deployed(app_base_url="http://example.test")

    def test_staging_is_as_strict_as_production(self) -> None:
        with pytest.raises(ValueError, match="SECRET_KEY"):
            self._deployed(app_env=AppEnvironment.STAGING, secret_key=SecretStr(""))

    def test_all_problems_are_reported_together(self) -> None:
        """One startup failure should name every problem, not just the first."""
        with pytest.raises(ValueError) as error:
            self._deployed(secret_key=SecretStr(""), database_url=SecretStr(""), deployment_key="")
        message = str(error.value)
        assert "SECRET_KEY" in message
        assert "DATABASE_URL" in message
        assert "DEPLOYMENT_KEY" in message


class TestLocalEnvironments:
    def test_development_starts_without_a_secret_key(self) -> None:
        settings = Settings(app_env=AppEnvironment.DEVELOPMENT)
        assert settings.resolved_secret_key()

    def test_generated_keys_differ_between_calls(self) -> None:
        settings = Settings(app_env=AppEnvironment.TEST)
        assert settings.resolved_secret_key() != settings.resolved_secret_key()


class TestDatabaseUrl:
    def test_bare_postgresql_scheme_is_pinned_to_psycopg(self) -> None:
        """SQLAlchemy resolves a bare 'postgresql' scheme to psycopg2, which is not
        installed, so the driver must be made explicit."""
        settings = Settings(database_url=SecretStr("postgresql://u:p@localhost:5432/db"))
        assert settings.database_url.get_secret_value().startswith("postgresql+psycopg://")

    def test_explicit_psycopg_scheme_is_preserved(self) -> None:
        url = "postgresql+psycopg://u:p@localhost:5432/db"
        settings = Settings(database_url=SecretStr(url))
        assert settings.database_url.get_secret_value() == url

    @pytest.mark.parametrize(
        "url",
        [
            "sqlite:///local.db",
            "mysql://u:p@localhost/db",
            "postgres://u:p@localhost/db",
        ],
    )
    def test_non_postgresql_urls_are_rejected(self, url: str) -> None:
        with pytest.raises(ValueError, match="postgresql"):
            Settings(database_url=SecretStr(url))


class TestSecretHandling:
    def test_secrets_are_not_present_in_the_representation(self) -> None:
        settings = Settings(
            secret_key=SecretStr("super-secret-value-aaaaaaaaaaaaaaaaaaa"),
            database_url=SecretStr("postgresql://user:hunter2@localhost:5432/db"),
        )
        rendered = repr(settings) + str(settings)
        assert "super-secret-value" not in rendered
        assert "hunter2" not in rendered

    def test_safe_summary_contains_no_secret_values(self) -> None:
        settings = Settings(
            app_env=AppEnvironment.TEST,
            secret_key=SecretStr("super-secret-value-aaaaaaaaaaaaaaaaaaa"),
            database_url=SecretStr("postgresql://user:hunter2@localhost:5432/db"),
        )
        rendered = str(settings.safe_summary())
        assert "super-secret-value" not in rendered
        assert "hunter2" not in rendered
        assert settings.safe_summary()["database_configured"] is True
        assert settings.safe_summary()["session_signing"] == "configured"

    def test_safe_summary_reports_an_ephemeral_signing_key(self) -> None:
        settings = Settings(app_env=AppEnvironment.TEST)
        assert settings.safe_summary()["session_signing"] == "ephemeral"


class TestLoadSettings:
    def test_invalid_configuration_raises_a_domain_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Callers depend on the domain vocabulary, not on pydantic."""
        monkeypatch.setenv("APP_ENV", "production")
        monkeypatch.setenv("SECRET_KEY", "")
        with pytest.raises(ConfigurationError):
            load_settings()

    def test_an_unknown_environment_name_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(app_env="prod")

    def test_an_invalid_log_level_is_rejected(self) -> None:
        with pytest.raises(ConfigurationError):
            load_settings(log_level="chatty")
