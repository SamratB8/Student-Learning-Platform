"""Inline dispatch, and the guarantee that it cannot reach a deployment.

ADR 0004 keeps an inline dispatcher for tests. The risk that creates is obvious and
worth pinning: inline execution has no durability, no retry, and no record, so a
deployment that quietly selected it would appear to work right up until work started
disappearing.
"""

from __future__ import annotations

import pytest

from learning_platform.application.ports.task_dispatcher import (
    DispatchReceipt,
    TaskDispatcher,
)
from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.domain.errors import ConfigurationError, InvariantViolation
from learning_platform.domain.tasks import TaskFailed, TaskType
from learning_platform.infrastructure.config.environments import AppEnvironment
from learning_platform.infrastructure.tasks.inline import InlineTaskDispatcher

DEMO = TaskType("demo.run")


def _registry(handler: object = None) -> TaskRegistry:
    registry = TaskRegistry()
    registry.register(DEMO, handler or (lambda _context: None))  # type: ignore[arg-type]
    return registry


class TestInlineIsRefusedWhenDeployed:
    """The whole reason this class exists before the behaviour tests."""

    @pytest.mark.parametrize("environment", [AppEnvironment.STAGING, AppEnvironment.PRODUCTION])
    def test_it_cannot_be_constructed_in_a_deployed_environment(
        self, environment: AppEnvironment
    ) -> None:
        with pytest.raises(ConfigurationError, match="deployed environment"):
            InlineTaskDispatcher(_registry(), environment=environment)

    @pytest.mark.parametrize("environment", [AppEnvironment.DEVELOPMENT, AppEnvironment.TEST])
    def test_it_is_available_locally(self, environment: AppEnvironment) -> None:
        assert InlineTaskDispatcher(_registry(), environment=environment) is not None

    def test_every_deployed_environment_is_covered_by_the_guard(self) -> None:
        """A new deployed environment must not slip past by being forgotten here."""
        deployed = [member for member in AppEnvironment if member.is_deployed]
        for environment in deployed:
            with pytest.raises(ConfigurationError):
                InlineTaskDispatcher(_registry(), environment=environment)

    def test_the_application_never_wires_inline_dispatch(self) -> None:
        """Composition uses the durable outbox. Inline is reachable only from a test.

        Read as source rather than by importing, so the check covers the intent of
        the composition root and not just whichever branch a test happened to run.
        """
        from pathlib import Path

        extensions = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "learning_platform"
            / "web"
            / "extensions.py"
        )
        assert "InlineTaskDispatcher" not in extensions.read_text(encoding="utf-8-sig")


class TestInlineDispatch:
    def test_it_satisfies_the_port(self) -> None:
        assert isinstance(InlineTaskDispatcher(_registry()), TaskDispatcher)

    def test_a_registered_handler_runs_immediately(self) -> None:
        seen: list[TaskContext] = []
        dispatcher = InlineTaskDispatcher(_registry(seen.append))

        receipt = dispatcher.dispatch(DEMO, {"id": "abc"})

        assert isinstance(receipt, DispatchReceipt)
        assert receipt.deduplicated is False
        assert len(seen) == 1
        assert seen[0].payload == {"id": "abc"}
        assert seen[0].attempt == 1

    def test_an_unregistered_task_is_refused(self) -> None:
        """Silently dropping work is worse than a loud failure."""
        with pytest.raises(TaskFailed):
            InlineTaskDispatcher(_registry()).dispatch(TaskType("demo.missing"), {})

    def test_a_failing_handler_propagates(self) -> None:
        """There is no durable row to mark failed and no retry to schedule."""

        def explode(_context: TaskContext) -> None:
            raise RuntimeError("handler failed")

        dispatcher = InlineTaskDispatcher(_registry(explode))
        with pytest.raises(RuntimeError, match="handler failed"):
            dispatcher.dispatch(DEMO, {})

    def test_payload_validation_runs_before_the_handler(self) -> None:
        called: list[TaskContext] = []
        dispatcher = InlineTaskDispatcher(_registry(called.append))

        with pytest.raises(InvariantViolation):
            dispatcher.dispatch(DEMO, {"secret": "x"})

        assert called == []

    def test_a_repeated_idempotency_key_does_not_run_twice(self) -> None:
        seen: list[TaskContext] = []
        dispatcher = InlineTaskDispatcher(_registry(seen.append))

        first = dispatcher.dispatch(DEMO, {}, idempotency_key="course-1-rev-2")
        second = dispatcher.dispatch(DEMO, {}, idempotency_key="course-1-rev-2")

        assert first.deduplicated is False
        assert second.deduplicated is True
        assert len(seen) == 1

    def test_an_unsupported_payload_version_is_refused(self) -> None:
        with pytest.raises(TaskFailed):
            InlineTaskDispatcher(_registry()).dispatch(DEMO, {}, payload_version=7)
