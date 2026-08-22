"""Logging must not emit secrets.

SECURITY_MODEL.md forbids tokens, cookies, authorization codes, signed URLs, private
keys, and message plaintext from reaching logs. Redaction is a processor rather than a
call-site convention, so these tests exercise the rendered output.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Iterator

import pytest

from learning_platform.infrastructure.config.settings import (
    AppEnvironment,
    LogFormat,
    Settings,
)
from learning_platform.infrastructure.observability.context import (
    bind_correlation_id,
    clear_correlation_id,
)
from learning_platform.infrastructure.observability.logging import (
    configure_logging,
    get_logger,
)


@pytest.fixture
def captured_logs() -> Iterator[io.StringIO]:
    """Configure JSON logging into a buffer, then restore the root logger."""
    settings = Settings(app_env=AppEnvironment.TEST, log_format=LogFormat.JSON)
    configure_logging(settings)

    stream = io.StringIO()
    root = logging.getLogger()
    formatter = root.handlers[0].formatter
    handler = logging.StreamHandler(stream)
    handler.setFormatter(formatter)
    previous = root.handlers[:]
    root.handlers = [handler]

    yield stream

    root.handlers = previous


class TestRedaction:
    def test_a_token_field_is_redacted(self, captured_logs: io.StringIO) -> None:
        get_logger("test").info("integration.connected", access_token="ya29.super-secret")
        output = captured_logs.getvalue()
        assert "ya29.super-secret" not in output
        assert "[redacted]" in output

    def test_the_field_name_survives_so_presence_is_visible(
        self, captured_logs: io.StringIO
    ) -> None:
        get_logger("test").info("event", refresh_token="abc")
        assert "refresh_token" in captured_logs.getvalue()

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("password", "hunter2"),
            ("cookie", "session=abc123"),
            ("authorization", "Bearer abc123"),
            ("auth_code", "4/0Ab-code"),
            ("signed_url", "https://storage.test/o?sig=abc123"),
            ("private_key", "-----BEGIN PRIVATE KEY-----"),
            ("message_plaintext", "hello there"),
            ("client_secret", "GOCSPX-abc"),
        ],
    )
    def test_every_forbidden_class_is_redacted(
        self, captured_logs: io.StringIO, field: str, value: str
    ) -> None:
        get_logger("test").info("event", **{field: value})
        assert value not in captured_logs.getvalue()

    def test_nested_secrets_are_redacted(self, captured_logs: io.StringIO) -> None:
        get_logger("test").info("event", payload={"user": "u-1", "api_key": "secret-abc"})
        output = captured_logs.getvalue()
        assert "secret-abc" not in output
        assert "u-1" in output

    def test_secrets_inside_a_list_are_redacted(self, captured_logs: io.StringIO) -> None:
        get_logger("test").info("event", items=[{"token": "abc-secret"}])
        assert "abc-secret" not in captured_logs.getvalue()

    def test_ordinary_fields_are_preserved(self, captured_logs: io.StringIO) -> None:
        get_logger("test").info("http.request", route="/healthz", status=200)
        output = captured_logs.getvalue()
        assert "/healthz" in output
        assert "200" in output


class TestLibraryLogsAlsoPassThroughRedaction:
    """Flask, SQLAlchemy, and Alembic log through the standard library.

    If those records bypassed the processor chain, redaction would cover only the
    project's own call sites, which is the least likely place for a leak.
    """

    def test_a_standard_library_record_is_rendered_as_json(
        self, captured_logs: io.StringIO
    ) -> None:
        logging.getLogger("some.library").warning("library message")
        output = captured_logs.getvalue()
        assert output.startswith("{")
        assert "library message" in output

    def test_extra_fields_on_a_library_record_are_redacted(
        self, captured_logs: io.StringIO
    ) -> None:
        logging.getLogger("some.library").warning("connecting", extra={"api_key": "leaked-value"})
        assert "leaked-value" not in captured_logs.getvalue()


class TestCorrelation:
    def test_a_bound_correlation_id_appears_on_every_record(
        self, captured_logs: io.StringIO
    ) -> None:
        token = bind_correlation_id("correlation-abc")
        try:
            get_logger("test").info("event")
        finally:
            clear_correlation_id(token)
        assert "correlation-abc" in captured_logs.getvalue()

    def test_no_correlation_id_is_emitted_outside_a_request(
        self, captured_logs: io.StringIO
    ) -> None:
        get_logger("test").info("event")
        assert "correlation_id" not in captured_logs.getvalue()
