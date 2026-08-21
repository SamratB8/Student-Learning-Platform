"""Environment-aware application settings.

Configuration is read once at startup, validated, and then treated as immutable. A
deployment that is missing something it needs fails at startup rather than serving
requests with an unsafe default, because a silently weak secret key is worse than an
application that will not boot.

Secret values are held as :class:`~pydantic.SecretStr`, so accidentally formatting a
settings object into a log line yields ``**********`` rather than a credential. Use
:meth:`Settings.safe_summary` for anything that is deliberately logged.
"""

from __future__ import annotations

import os
import secrets
from collections.abc import Mapping
from enum import StrEnum
from typing import Any, Final, Self
from urllib.parse import urlparse

from pydantic import Field, SecretStr, ValidationError, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.environments import AppEnvironment
from learning_platform.infrastructure.config.hosting import resolve_app_environment

__all__ = [
    "AppEnvironment",
    "LogFormat",
    "Settings",
    "load_hosted_settings",
    "load_settings",
]

_MINIMUM_SECRET_KEY_LENGTH: Final = 32

# Values that appear in examples and tutorials. Rejecting them outside development
# stops the most common way a placeholder reaches production.
_FORBIDDEN_SECRET_KEYS: Final[frozenset[str]] = frozenset(
    {
        "",
        "change-me",
        "changeme",
        "dev",
        "development",
        "secret",
        "secret-key",
        "test",
        "please-change-me",
    }
)

_SUPPORTED_DATABASE_SCHEMES: Final[frozenset[str]] = frozenset({"postgresql", "postgresql+psycopg"})


class LogFormat(StrEnum):
    """How log records are rendered."""

    CONSOLE = "console"
    """Human-readable, for a developer's terminal."""

    JSON = "json"
    """One JSON object per line, for log aggregation."""


class Settings(BaseSettings):
    """Validated deployment configuration.

    Field names map to the upper-case environment variables in ``.env.example``.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
    )

    app_env: AppEnvironment = AppEnvironment.DEVELOPMENT
    """Selects environment-appropriate strictness. Never inferred from a hostname."""

    deployment_key: str = Field(default="", max_length=64)
    """Which deployment configuration applies, for example ``cts``.

    Deployment data, never a value that domain logic branches on.
    """

    app_base_url: str = "http://127.0.0.1:5000"
    """The externally visible origin. Used to build absolute URLs and to constrain
    redirects; it is not derived from request headers, which are attacker-controlled.

    The default uses 127.0.0.1 rather than localhost, matching the development
    database URL: on Windows, localhost resolves to ``::1`` first and stalls against
    a service published on IPv4 loopback only.
    """

    secret_key: SecretStr = SecretStr("")
    """Signing key for sessions and other tamper-evident values."""

    database_url: SecretStr = SecretStr("")
    """PostgreSQL connection URL. Secret because it embeds a password."""

    database_pool_size: int = Field(default=5, ge=1, le=50)
    """Connections held per process. Small by default: ADR 0002 assumes many
    short-lived serverless invocations rather than a few long-lived processes."""

    database_pool_timeout_seconds: int = Field(default=10, ge=1, le=120)
    """How long to wait for a connection from the pool."""

    database_connect_timeout_seconds: int = Field(default=10, ge=2, le=60)
    """How long to wait for the TCP connection and handshake to a new connection.

    Bounded deliberately. An unreachable host does not always refuse promptly, and
    under ADR 0002 an unbounded wait would hold a serverless invocation open until
    the platform killed it, turning a database outage into an exhausted request
    budget. The floor is 2 because libpq silently raises anything lower.
    """

    log_level: str = "INFO"
    log_format: LogFormat | None = None
    """Defaults to console in development and test, JSON when deployed."""

    @field_validator("log_level")
    @classmethod
    def _validate_log_level(cls, value: str) -> str:
        normalized = value.strip().upper()
        allowed = {"CRITICAL", "ERROR", "WARNING", "INFO", "DEBUG"}
        if normalized not in allowed:
            raise ValueError(f"LOG_LEVEL must be one of {sorted(allowed)}")
        return normalized

    @field_validator("app_base_url")
    @classmethod
    def _validate_base_url(cls, value: str) -> str:
        parsed = urlparse(value)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("APP_BASE_URL must be an absolute http or https URL")
        return value.rstrip("/")

    @field_validator("database_url")
    @classmethod
    def _validate_database_url(cls, value: SecretStr) -> SecretStr:
        raw = value.get_secret_value().strip()
        if not raw:
            return SecretStr("")
        parsed = urlparse(raw)
        if parsed.scheme not in _SUPPORTED_DATABASE_SCHEMES:
            raise ValueError(
                "DATABASE_URL must use the postgresql or postgresql+psycopg scheme; "
                "PostgreSQL is the only supported relational target"
            )
        # Pin the driver explicitly. SQLAlchemy's bare 'postgresql' scheme resolves to
        # psycopg2, which this project does not install.
        if parsed.scheme == "postgresql":
            raw = raw.replace("postgresql://", "postgresql+psycopg://", 1)
        return SecretStr(raw)

    @model_validator(mode="after")
    def _validate_environment_requirements(self) -> Self:
        if not self.app_env.is_deployed:
            return self

        problems: list[str] = []

        secret = self.secret_key.get_secret_value()
        if secret.strip().lower() in _FORBIDDEN_SECRET_KEYS:
            problems.append("SECRET_KEY is missing or is a known placeholder value")
        elif len(secret) < _MINIMUM_SECRET_KEY_LENGTH:
            problems.append(f"SECRET_KEY must be at least {_MINIMUM_SECRET_KEY_LENGTH} characters")

        if not self.database_url.get_secret_value():
            problems.append("DATABASE_URL is required")

        if not self.deployment_key:
            problems.append("DEPLOYMENT_KEY is required")

        if urlparse(self.app_base_url).scheme != "https":
            problems.append("APP_BASE_URL must use https")

        if problems:
            raise ValueError(
                f"invalid configuration for {self.app_env.value}: " + "; ".join(problems)
            )
        return self

    @property
    def debug(self) -> bool:
        """Debug behavior is available only in development.

        Never derived from a ``DEBUG`` environment variable, so a stray variable
        cannot turn on the interactive debugger and tracebacks in a deployed
        environment.
        """
        return self.app_env is AppEnvironment.DEVELOPMENT

    @property
    def testing(self) -> bool:
        return self.app_env is AppEnvironment.TEST

    @property
    def effective_log_format(self) -> LogFormat:
        if self.log_format is not None:
            return self.log_format
        return LogFormat.JSON if self.app_env.is_deployed else LogFormat.CONSOLE

    @property
    def database_configured(self) -> bool:
        return bool(self.database_url.get_secret_value())

    def resolved_secret_key(self) -> str:
        """Return the signing key, generating an ephemeral one where that is safe.

        In development and test an unset key becomes a random per-process value. That
        invalidates sessions on restart, which is a mild annoyance locally and is
        preferable to shipping a shared default that could reach a real deployment.
        Deployed environments never reach this path: validation already rejected them.
        """
        secret = self.secret_key.get_secret_value()
        if secret:
            return secret
        if self.app_env.is_deployed:  # pragma: no cover - unreachable after validation
            raise ConfigurationError("SECRET_KEY is required in deployed environments")
        return secrets.token_urlsafe(_MINIMUM_SECRET_KEY_LENGTH)

    def safe_summary(self) -> dict[str, Any]:
        """Non-secret configuration facts, suitable for a startup log line.

        Reports only presence and mode, never any part of a secret value. Field names
        deliberately avoid words such as "secret" and "key", because the log redactor
        matches on field names and would replace an otherwise useful boolean.
        """
        return {
            "app_env": self.app_env.value,
            "deployment_key": self.deployment_key or None,
            "app_base_url": self.app_base_url,
            "log_level": self.log_level,
            "log_format": self.effective_log_format.value,
            "database_configured": self.database_configured,
            "session_signing": (
                "configured" if self.secret_key.get_secret_value() else "ephemeral"
            ),
            "debug": self.debug,
        }


def load_settings(**overrides: Any) -> Settings:
    """Build settings from the environment.

    Raises:
        ConfigurationError: if the environment is missing, invalid, or hosted but
            ambiguous.

    The application environment is resolved before validation rather than left to the
    field default. ``APP_ENV`` defaults to development, which is correct locally and
    unsafe anywhere else, so :func:`resolve_app_environment` decides it from the
    platform's own environment variables and fails closed when a hosted deployment
    cannot be identified. See ``hosting.py`` for the rule.

    An ``app_env`` passed in ``overrides`` is respected as-is. Overrides come from
    calling code that stated the value deliberately, not from an environment that
    might have omitted it, so there is no silent fallback to remove.

    Pydantic's validation error is translated into a domain error so callers depend
    on the domain vocabulary rather than on pydantic.

    The message is rebuilt from ``errors(include_input=False)`` rather than by
    formatting the exception. Pydantic's default rendering echoes the offending
    input, and for a model-level validator that input is the raw settings dict,
    before ``SecretStr`` wrapping. Formatting it would put the ``DATABASE_URL``
    password into the startup error and therefore into the logs.

    The pydantic error is also suppressed from the exception chain with ``from None``.
    Sanitising only the message is not enough: a chained ``__cause__`` is rendered in
    full whenever a traceback is printed, and pydantic's own rendering of that cause
    echoes each rejected value. This was observed on a real Vercel preview, where a
    failed boot printed the partial contents of ``DATABASE_URL`` into the platform's
    runtime logs. Nothing is lost by dropping the chain, because the rebuilt message
    already names every offending variable and why it was rejected.
    """
    return _build_settings(assume_hosted=False, overrides=overrides)


def load_hosted_settings(**overrides: Any) -> Settings:
    """Build settings for a process that is definitely a hosted deployment.

    Raises:
        ConfigurationError: if the environment cannot be identified as a specific
            deployed environment.

    Identical to :func:`load_settings` except that being hosted is asserted rather
    than detected. The hosting entry point uses this, because the fact that the entry
    point was imported at all proves a platform imported it.

    This matters because every Vercel marker variable depends on the project's
    "system environment variables" setting being enabled. Were it switched off, plain
    detection would see no markers, conclude the process is local, and hand back
    development defaults on a public URL. Asserting the fact removes that dependency.
    """
    return _build_settings(assume_hosted=True, overrides=overrides)


def _build_settings(*, assume_hosted: bool, overrides: dict[str, Any]) -> Settings:
    """Resolve the environment, then validate the whole configuration."""
    if "app_env" not in overrides:
        overrides = dict(overrides)
        overrides["app_env"] = resolve_app_environment(os.environ, assume_hosted=assume_hosted)

    try:
        return Settings(**overrides)
    except ValidationError as exc:
        problems = "; ".join(
            _describe_validation_error(error)
            for error in exc.errors(include_input=False, include_url=False)
        )
        raise ConfigurationError(f"Invalid application configuration: {problems}") from None
    except ValueError as exc:
        # A non-pydantic ValueError carries only what our own code put in it.
        raise ConfigurationError(f"Invalid application configuration: {exc}") from exc


def _describe_validation_error(error: Mapping[str, Any]) -> str:
    """Render one pydantic error as 'FIELD: message', with no input value."""
    location = ".".join(str(part) for part in error.get("loc", ()))
    message = str(error.get("msg", "is invalid"))
    return f"{location.upper()}: {message}" if location else message
