"""Task dispatch seam.

ADR 0004 is open, so these tests fix the contract that any future runtime must
honour, not the behaviour of a chosen queue.
"""

from __future__ import annotations

import pytest

from learning_platform.application.ports.task_dispatcher import (
    TaskDispatcher,
    TaskName,
    TaskPayload,
    validate_task_payload,
)
from learning_platform.domain.errors import InvariantViolation
from learning_platform.infrastructure.tasks.inline import InlineTaskDispatcher


class TestTaskName:
    @pytest.mark.parametrize("name", ["classroom.sync_course", "archive.build.manifest"])
    def test_dotted_lowercase_names_are_accepted(self, name: str) -> None:
        assert str(TaskName(name)) == name

    @pytest.mark.parametrize("name", ["sync", "Classroom.Sync", "classroom sync", ""])
    def test_other_shapes_are_rejected(self, name: str) -> None:
        with pytest.raises(InvariantViolation):
            TaskName(name)


class TestPayloadValidation:
    def test_an_ordinary_payload_passes(self) -> None:
        validate_task_payload({"course_id": "c-1", "attempt": 2})

    @pytest.mark.parametrize("key", ["access_token", "password", "private_key", "cookie"])
    def test_a_sensitive_field_is_refused(self, key: str) -> None:
        """A payload crosses a process boundary and is written to durable storage."""
        with pytest.raises(InvariantViolation, match="sensitive"):
            validate_task_payload({key: "value"})


class TestInlineDispatcher:
    def test_it_satisfies_the_port(self) -> None:
        assert isinstance(InlineTaskDispatcher(), TaskDispatcher)

    def test_a_registered_handler_runs_with_its_payload(self) -> None:
        received: list[TaskPayload] = []
        dispatcher = InlineTaskDispatcher()
        dispatcher.register(TaskName("demo.run"), received.append)

        dispatcher.dispatch(TaskName("demo.run"), {"id": "abc"})

        assert received == [{"id": "abc"}]

    def test_an_unregistered_task_fails_loudly_when_strict(self) -> None:
        """Silently dropping work is worse than a loud failure."""
        with pytest.raises(InvariantViolation, match="no handler"):
            InlineTaskDispatcher(strict=True).dispatch(TaskName("demo.missing"), {})

    def test_an_unregistered_task_is_tolerated_when_not_strict(self) -> None:
        InlineTaskDispatcher(strict=False).dispatch(TaskName("demo.missing"), {})

    def test_registering_a_name_twice_is_refused(self) -> None:
        """Otherwise dispatch would depend on import order."""
        dispatcher = InlineTaskDispatcher()
        dispatcher.register(TaskName("demo.run"), lambda _payload: None)
        with pytest.raises(InvariantViolation, match="already has a handler"):
            dispatcher.register(TaskName("demo.run"), lambda _payload: None)

    def test_a_failing_handler_propagates(self) -> None:
        """Inline dispatch has no retry and no dead-letter state."""

        def explode(_payload: TaskPayload) -> None:
            raise RuntimeError("handler failed")

        dispatcher = InlineTaskDispatcher()
        dispatcher.register(TaskName("demo.explode"), explode)

        with pytest.raises(RuntimeError, match="handler failed"):
            dispatcher.dispatch(TaskName("demo.explode"), {})

    def test_payload_validation_runs_before_the_handler(self) -> None:
        called: list[TaskPayload] = []
        dispatcher = InlineTaskDispatcher()
        dispatcher.register(TaskName("demo.run"), called.append)

        with pytest.raises(InvariantViolation):
            dispatcher.dispatch(TaskName("demo.run"), {"secret": "x"})

        assert called == []
