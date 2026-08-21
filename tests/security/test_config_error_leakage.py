"""A configuration failure must not disclose the values it rejected.

Startup errors are logged, and in a deployed environment they may reach an operator's
aggregator or a crash report. Pydantic's default error rendering echoes the offending
input, and for a model-level validator that input is the raw settings mapping, before
``SecretStr`` wrapping. That put the ``DATABASE_URL`` password into the message.

These tests pin the fix. The canaries are deliberately short and distinctive so a
partial disclosure through a truncated repr is caught, not just a whole-value one.
"""

from __future__ import annotations

import pytest

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.settings import load_settings

PASSWORD_CANARY = "pw0canary"
SECRET_CANARY = "sk0canary"


def _production_environment(monkeypatch: pytest.MonkeyPatch, **overrides: str) -> None:
    values = {
        "APP_ENV": "production",
        "DEPLOYMENT_KEY": "test",
        "APP_BASE_URL": "https://example.test",
        "SECRET_KEY": SECRET_CANARY,
        "DATABASE_URL": f"postgresql://user:{PASSWORD_CANARY}@127.0.0.1:5432/db",
    }
    values.update(overrides)
    for name, value in values.items():
        monkeypatch.setenv(name, value)


class TestConfigurationErrorLeakage:
    def test_a_rejected_secret_key_is_not_echoed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SECRET_KEY here is too short, so validation fails while holding a real value."""
        _production_environment(monkeypatch)

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        assert SECRET_CANARY not in str(error.value)

    def test_the_database_password_is_not_echoed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _production_environment(monkeypatch)

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        assert PASSWORD_CANARY not in str(error.value)

    def test_no_fragment_of_the_password_survives(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """A truncated repr previously leaked the tail of the connection string."""
        _production_environment(monkeypatch)

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        message = str(error.value)
        for length in range(4, len(PASSWORD_CANARY) + 1):
            assert PASSWORD_CANARY[:length] not in message
            assert PASSWORD_CANARY[-length:] not in message

    def test_a_rejected_database_url_is_not_echoed(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """The field validator rejects the scheme, so the value reaches an error path."""
        _production_environment(
            monkeypatch, DATABASE_URL=f"mysql://user:{PASSWORD_CANARY}@127.0.0.1/db"
        )

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        assert PASSWORD_CANARY not in str(error.value)

    def test_the_message_still_names_the_offending_variable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Redaction must not make the error useless to whoever has to fix it."""
        _production_environment(monkeypatch, DATABASE_URL="", SECRET_KEY="")

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        message = str(error.value)
        assert "SECRET_KEY" in message
        assert "DATABASE_URL" in message

    def test_a_field_level_failure_names_its_field(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _production_environment(monkeypatch, LOG_LEVEL="chatty")

        with pytest.raises(ConfigurationError) as error:
            load_settings()

        assert "LOG_LEVEL" in str(error.value)
