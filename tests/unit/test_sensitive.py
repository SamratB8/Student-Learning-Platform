"""The field names that must never be recorded.

SECURITY_MODEL.md lists the classes of value that may not reach logs or audit
records. This is the test for the rule that enforces it.
"""

from __future__ import annotations

import pytest

from learning_platform.domain.sensitive import REDACTED, is_sensitive_key, redact_mapping


class TestSensitiveKeys:
    @pytest.mark.parametrize(
        "key",
        [
            "password",
            "passphrase",
            "user_password",
            "secret",
            "client_secret",
            "SECRET_KEY",
            "access_token",
            "refresh_token",
            "id_token",
            "api_key",
            "apikey",
            "private_key",
            "recovery_key",
            "credentials",
            "authorization",
            "Authorization",
            "cookie",
            "Set-Cookie",
            "auth_code",
            "otp",
            "signature",
            "signed_url",
            "message_plaintext",
            "ciphertext",
        ],
    )
    def test_sensitive_names_are_detected(self, key: str) -> None:
        assert is_sensitive_key(key) is True

    @pytest.mark.parametrize(
        "key",
        [
            "user_id",
            "action",
            "status",
            "duration_ms",
            "route",
            "method",
            "correlation_id",
            "branch",
            "resource_id",
            "keyboard_layout",
            "monkey",
        ],
    )
    def test_ordinary_names_are_left_alone(self, key: str) -> None:
        assert is_sensitive_key(key) is False


class TestRedactMapping:
    def test_sensitive_values_are_replaced_and_others_kept(self) -> None:
        result = redact_mapping({"user_id": "u-1", "access_token": "ya29.secret"})
        assert result == {"user_id": "u-1", "access_token": REDACTED}

    def test_the_key_survives_so_presence_is_still_visible(self) -> None:
        assert "password" in redact_mapping({"password": "hunter2"})

    def test_nested_mappings_are_redacted(self) -> None:
        result = redact_mapping({"outer": {"inner": {"api_key": "abc"}}})
        assert result == {"outer": {"inner": {"api_key": REDACTED}}}

    def test_the_input_is_not_mutated(self) -> None:
        original = {"password": "hunter2"}
        redact_mapping(original)
        assert original == {"password": "hunter2"}
