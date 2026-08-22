"""Inline task dispatch: runs the handler immediately, in the caller.

This is the development and test implementation, and it is deliberately the only one
that exists while ADR 0004 is open. It gives the port a real implementation so the
seam is exercised, without committing the project to a queue.

It is not a production strategy. Inline execution ties the caller's latency to the
task, offers no retry, and dies with the process. Any workload that could exceed a
request timeout must wait for ADR 0004 rather than lean on this.
"""

from __future__ import annotations

from collections.abc import Callable

from learning_platform.application.ports.task_dispatcher import (
    TaskName,
    TaskPayload,
    validate_task_payload,
)
from learning_platform.domain.errors import InvariantViolation
from learning_platform.infrastructure.observability.logging import get_logger

__all__ = ["InlineTaskDispatcher", "TaskHandler"]

type TaskHandler = Callable[[TaskPayload], None]

_logger = get_logger(__name__)


class InlineTaskDispatcher:
    """Executes registered handlers synchronously.

    Implements ``application.ports.task_dispatcher.TaskDispatcher``.
    """

    def __init__(self, *, strict: bool = True) -> None:
        """
        Args:
            strict: whether dispatching an unregistered task name is an error.
                True in development and tests, so a typo in a task name surfaces
                immediately rather than becoming silently dropped work.
        """
        self._handlers: dict[str, TaskHandler] = {}
        self._strict = strict

    def register(self, name: TaskName, handler: TaskHandler) -> None:
        """Bind a handler to a task name.

        Raises:
            InvariantViolation: if the name is already registered. Silently replacing
                a handler would make dispatch depend on import order.
        """
        if name in self._handlers:
            raise InvariantViolation(f"task {name!r} already has a handler")
        self._handlers[name] = handler

    def dispatch(self, name: TaskName, payload: TaskPayload) -> None:
        """Run the handler for ``name`` immediately."""
        validate_task_payload(payload)

        handler = self._handlers.get(name)
        if handler is None:
            if self._strict:
                raise InvariantViolation(f"no handler registered for task {name!r}")
            _logger.warning("task.unhandled", task_name=str(name))
            return

        _logger.info("task.started", task_name=str(name))
        try:
            handler(payload)
        except Exception:
            # Logged with the task name and re-raised. Inline dispatch has no retry
            # and no dead-letter state, so the caller must see the failure.
            _logger.exception("task.failed", task_name=str(name))
            raise
        _logger.info("task.completed", task_name=str(name))
