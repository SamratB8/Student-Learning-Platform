"""The registry is what stops a database row from choosing code.

A task type arrives as text out of a table. These tests pin that the only thing that
text can do is match something registered in Python, or be refused.
"""

from __future__ import annotations

import pytest

from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.tasks import TaskFailed, TaskFailureKind, TaskType

DEMO = TaskType("demo.run")
OTHER = TaskType("demo.other")


def _noop(_context: TaskContext) -> None:
    return None


class TestRegistration:
    def test_a_registered_type_resolves_to_its_handler(self) -> None:
        registry = TaskRegistry()
        registry.register(DEMO, _noop)
        assert registry.resolve(DEMO, 1) is _noop

    def test_registration_is_visible(self) -> None:
        registry = TaskRegistry()
        registry.register(DEMO, _noop)
        assert registry.is_registered(DEMO) is True
        assert registry.is_registered(OTHER) is False

    def test_registering_twice_is_refused(self) -> None:
        """Overwriting would make which handler runs depend on import order."""
        registry = TaskRegistry()
        registry.register(DEMO, _noop)
        with pytest.raises(InvariantViolation, match="already registered"):
            registry.register(DEMO, _noop)

    def test_a_second_registration_does_not_replace_the_first(self) -> None:
        def replacement(_context: TaskContext) -> None:
            return None

        registry = TaskRegistry()
        registry.register(DEMO, _noop)
        with pytest.raises(InvariantViolation):
            registry.register(DEMO, replacement)
        assert registry.resolve(DEMO, 1) is _noop

    def test_declaring_no_payload_version_is_refused(self) -> None:
        registry = TaskRegistry()
        with pytest.raises(InvariantViolation, match="payload version"):
            registry.register(DEMO, _noop, payload_versions=())

    def test_version_zero_is_refused(self) -> None:
        registry = TaskRegistry()
        with pytest.raises(InvariantViolation, match="start at one"):
            registry.register(DEMO, _noop, payload_versions=(0,))

    def test_registrations_are_readable_for_diagnostics(self) -> None:
        registry = TaskRegistry()
        registry.register(DEMO, _noop)
        assert set(registry.registrations()) == {"demo.run"}

    def test_the_returned_registrations_are_a_copy(self) -> None:
        """Handing out the live mapping would let a caller register by mutation."""
        registry = TaskRegistry()
        registry.register(DEMO, _noop)
        registry.registrations().clear()  # type: ignore[attr-defined]
        assert registry.is_registered(DEMO) is True


class TestResolution:
    def test_an_unknown_type_is_a_terminal_failure(self) -> None:
        """Not an exception to crash the drain on: a rollback produces this legitimately."""
        registry = TaskRegistry()
        with pytest.raises(TaskFailed) as error:
            registry.resolve(TaskType("never.registered"), 1)

        assert error.value.kind is TaskFailureKind.INVALID_PAYLOAD
        assert error.value.kind.is_retryable is False
        assert error.value.code == "unknown_task_type"

    def test_an_unsupported_payload_version_is_a_terminal_failure(self) -> None:
        registry = TaskRegistry()
        registry.register(DEMO, _noop, payload_versions=(1,))

        with pytest.raises(TaskFailed) as error:
            registry.resolve(DEMO, 2)

        assert error.value.code == "unsupported_payload_version"
        assert error.value.kind.is_retryable is False

    def test_a_handler_may_declare_several_payload_versions(self) -> None:
        """A rollout that changed a payload shape must not strand pending rows."""
        registry = TaskRegistry()
        registry.register(DEMO, _noop, payload_versions=(1, 2))

        assert registry.resolve(DEMO, 1) is _noop
        assert registry.resolve(DEMO, 2) is _noop
        with pytest.raises(TaskFailed):
            registry.resolve(DEMO, 3)


class TestNoDynamicResolution:
    """The registry never turns a string into code it was not given."""

    @pytest.mark.parametrize(
        "task_type", ["os.system", "builtins.eval", "learning_platform.worker"]
    )
    def test_an_importable_looking_name_resolves_to_nothing(self, task_type: str) -> None:
        registry = TaskRegistry()
        with pytest.raises(TaskFailed, match="task failed"):
            registry.resolve(TaskType(task_type), 1)

    def test_an_empty_registry_can_run_nothing_at_all(self) -> None:
        registry = TaskRegistry()
        assert registry.registrations() == {}
        with pytest.raises(TaskFailed):
            registry.resolve(DEMO, 1)


class TestShippedRegistry:
    def test_the_deployment_registry_contains_only_maintenance(self) -> None:
        """Phase 1B ships no product tasks. This fails if one is smuggled in."""
        from learning_platform.worker import build_task_registry

        assert set(build_task_registry().registrations()) == {"maintenance.verify_dispatch"}

    def test_the_verification_task_does_nothing_and_succeeds(self) -> None:
        from learning_platform.domain.identifiers import new_internal_id
        from learning_platform.worker import build_task_registry
        from learning_platform.worker.maintenance import VERIFY_DISPATCH

        handler = build_task_registry().resolve(VERIFY_DISPATCH, 1)
        handler(
            TaskContext(
                task_id=new_internal_id(),
                task_type=VERIFY_DISPATCH,
                payload={},
                payload_version=1,
                attempt=1,
                max_attempts=5,
            )
        )
