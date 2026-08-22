"""Structured logging for task execution.

Implements the runner's observer port, which exists so the application layer can
report progress without importing a logger.

What is logged is chosen narrowly: identity, type, state, attempt, correlation, and
timing. Never the payload. A payload is small and looks harmless, which is exactly
why logging it by default would eventually put an identifier trail for every synced
record into the log aggregator, and the redaction pipeline only catches field names
it recognises.
"""

from __future__ import annotations

from contextvars import Token

from learning_platform.application.ports.task_store import ClaimedTask
from learning_platform.domain.tasks import TaskState
from learning_platform.infrastructure.observability.context import (
    bind_correlation_id,
    clear_correlation_id,
)
from learning_platform.infrastructure.observability.logging import get_logger

__all__ = ["LoggingTaskObserver"]

_logger = get_logger(__name__)


class LoggingTaskObserver:
    """Logs task lifecycle events and binds the task's correlation identifier.

    Implements ``application.tasks.runner.TaskObserver``.

    Binding matters as much as logging: a handler's own log lines, and any audit
    event it records, then carry the identifier of the request that originally asked
    for the work, so a user's report can be followed from the request through to work
    that ran minutes later in a different invocation.
    """

    def __init__(self) -> None:
        self._tokens: dict[str, Token[str | None]] = {}

    def started(self, task: ClaimedTask) -> None:
        if task.correlation_id is not None:
            self._tokens[str(task.task_id)] = bind_correlation_id(task.correlation_id)

        _logger.info(
            "task.started",
            task_id=str(task.task_id),
            task_type=str(task.task_type),
            attempt=task.attempt,
            max_attempts=task.max_attempts,
        )

    def finished(
        self,
        task: ClaimedTask,
        *,
        state: TaskState,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        event = "task.finished" if state is TaskState.SUCCEEDED else "task.failed"
        # Exhausted retries mean work was genuinely lost rather than merely refused,
        # so it is the one outcome raised above informational level.
        log = _logger.error if state is TaskState.EXHAUSTED else _logger.info
        log(
            event,
            task_id=str(task.task_id),
            task_type=str(task.task_type),
            state=state.value,
            attempt=task.attempt,
            duration_ms=duration_ms,
            error_code=error_code,
        )

        token = self._tokens.pop(str(task.task_id), None)
        if token is not None:
            clear_correlation_id(token)
