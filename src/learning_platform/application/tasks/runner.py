"""Claiming due work, running it, and recording what happened.

This is the execution half of ADR 0004. It is deliberately ordinary Python: it takes
a unit of work, a registry, and a clock, and it can be exercised in a unit test with
none of PostgreSQL, Flask, HTTP, or a queue present. The delivery mechanism's only
job is to call :meth:`TaskRunner.drain`.

Two ordering decisions matter.

*The claim commits before any handler runs.* A lease that is only visible inside an
uncommitted transaction protects nothing, because a second runner cannot see it.

*Each outcome is recorded in its own transaction, separate from the handler's own
work.* A handler that fails must not be able to roll back the record of its failure,
or the attempt counter would never advance and the task would retry for ever.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol, Self, runtime_checkable

from learning_platform.application.ports.task_store import ClaimedTask, TaskDispatchStore
from learning_platform.application.ports.unit_of_work import UnitOfWork
from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.domain.clock import Clock
from learning_platform.domain.tasks import (
    RetryPolicy,
    TaskFailed,
    TaskFailureKind,
    TaskState,
)

__all__ = ["DrainReport", "TaskObserver", "TaskRunner", "TaskUnitOfWork"]

_UNHANDLED_ERROR_CODE = "unhandled_exception"


@runtime_checkable
class TaskUnitOfWork(UnitOfWork, Protocol):
    """A transaction that can reach the dispatch store."""

    @property
    def task_store(self) -> TaskDispatchStore:
        """The store bound to this transaction."""
        ...

    def __enter__(self) -> Self:
        """Begin the transaction."""
        ...


@runtime_checkable
class TaskObserver(Protocol):
    """Reports what the runner is doing, without the runner importing a logger.

    A port rather than a direct call, because this layer may not import structlog or
    anything else framework-shaped. It also gives tests somewhere to assert that a
    failure was reported without capturing log output.
    """

    def started(self, task: ClaimedTask) -> None:
        """A task has been claimed and is about to run."""
        ...

    def finished(
        self,
        task: ClaimedTask,
        *,
        state: TaskState,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        """A task has reached ``state``. Always called, including on failure."""
        ...


@dataclass(frozen=True, slots=True)
class DrainReport:
    """What one drain did.

    Counts only. Not a list of tasks, because this is returned over HTTP to whatever
    triggered the drain, and identifiers of work belonging to other people are not
    something an invocation endpoint should hand back.
    """

    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    exhausted: int = 0
    failed: int = 0

    @property
    def is_empty(self) -> bool:
        """Whether there was nothing due."""
        return self.claimed == 0


class _NullObserver:
    """Reports nothing. The default, so the runner is usable in a test with no setup."""

    def started(self, task: ClaimedTask) -> None:
        return None

    def finished(
        self,
        task: ClaimedTask,
        *,
        state: TaskState,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        return None


class TaskRunner:
    """Executes work that is due."""

    def __init__(
        self,
        *,
        unit_of_work: Callable[[], TaskUnitOfWork],
        registry: TaskRegistry,
        clock: Clock,
        retry_policy: RetryPolicy | None = None,
        lease_seconds: int = 300,
        batch_limit: int = 10,
        observer: TaskObserver | None = None,
    ) -> None:
        """
        Args:
            lease_seconds: how long a claim is honoured before another runner may
                take the task back. Should exceed the longest plausible handler and
                stay within the platform's own invocation limit: a lease longer than
                the invocation that holds it would leave work stalled for no reason,
                and one shorter would let a second runner start work that is still
                in progress.
            batch_limit: how many tasks one drain claims. Bounded so a drain finishes
                well inside an invocation budget rather than being killed mid-batch.
        """
        if lease_seconds < 1:
            raise ValueError("a lease must last at least one second")
        if batch_limit < 1:
            raise ValueError("a drain must be allowed to claim at least one task")

        self._unit_of_work = unit_of_work
        self._registry = registry
        self._clock = clock
        self._retry_policy = retry_policy or RetryPolicy()
        self._lease_seconds = lease_seconds
        self._batch_limit = batch_limit
        self._observer: TaskObserver = observer or _NullObserver()

    def drain(self, *, limit: int | None = None) -> DrainReport:
        """Claim due work, run it, and report what happened.

        Never raises because a handler failed: a failing task is recorded and the
        drain continues to the next one. One poisoned task must not stop every other
        piece of work in the system, and the caller is usually a scheduled invocation
        that has nowhere useful to put an exception.
        """
        batch = min(limit or self._batch_limit, self._batch_limit)
        claimed = self._claim(batch)
        if not claimed:
            return DrainReport()

        outcomes: list[TaskState] = [self._execute(task) for task in claimed]

        return DrainReport(
            claimed=len(claimed),
            succeeded=outcomes.count(TaskState.SUCCEEDED),
            retried=outcomes.count(TaskState.PENDING),
            exhausted=outcomes.count(TaskState.EXHAUSTED),
            failed=outcomes.count(TaskState.FAILED),
        )

    def _claim(self, limit: int) -> list[ClaimedTask]:
        """Lease a batch, committing before anything runs."""
        with self._unit_of_work() as unit_of_work:
            return list(
                unit_of_work.task_store.claim_due(
                    now=self._clock.now(),
                    limit=limit,
                    lease_seconds=self._lease_seconds,
                )
            )

    def _execute(self, task: ClaimedTask) -> TaskState:
        """Run one claimed task and record its outcome. Returns the state reached."""
        self._observer.started(task)
        started_at = time.perf_counter()

        try:
            handler = self._registry.resolve(task.task_type, task.payload_version)
        except TaskFailed as failure:
            return self._record_failure(task, failure, started_at)

        try:
            handler(
                TaskContext(
                    task_id=task.task_id,
                    task_type=task.task_type,
                    payload=task.payload,
                    payload_version=task.payload_version,
                    attempt=task.attempt,
                    max_attempts=task.max_attempts,
                    correlation_id=task.correlation_id,
                )
            )
        except TaskFailed as failure:
            return self._record_failure(task, failure, started_at)
        except Exception:
            # An unclassified exception is assumed retryable. The alternative, giving
            # up on anything a handler did not label, would silently discard work
            # whenever an author forgot to classify a transient fault.
            #
            # Only the class of failure is recorded. The exception itself is not
            # persisted: its message routinely quotes the value that caused it, and a
            # task payload sits in the same row.
            return self._record_failure(
                task,
                TaskFailed(TaskFailureKind.INFRASTRUCTURE, _UNHANDLED_ERROR_CODE),
                started_at,
            )

        return self._record_success(task, started_at)

    def _record_success(self, task: ClaimedTask, started_at: float) -> TaskState:
        now = self._clock.now()
        with self._unit_of_work() as unit_of_work:
            unit_of_work.task_store.record_outcome(
                task_id=task.task_id, state=TaskState.SUCCEEDED, now=now
            )
        self._observer.finished(
            task, state=TaskState.SUCCEEDED, duration_ms=_elapsed_ms(started_at)
        )
        return TaskState.SUCCEEDED

    def _record_failure(
        self, task: ClaimedTask, failure: TaskFailed, started_at: float
    ) -> TaskState:
        now = self._clock.now()
        retryable = failure.kind.is_retryable and self._retry_policy.has_attempts_remaining(
            attempt=task.attempt, max_attempts=task.max_attempts
        )

        if retryable:
            state = TaskState.PENDING
            available_at = self._retry_policy.next_attempt_at(attempt=task.attempt, now=now)
        else:
            # Exhausted and refused are kept apart on purpose. Refused means this code
            # can never run this row; exhausted means it could have, and work was
            # lost. Only the second is an operational alarm.
            state = TaskState.FAILED if not failure.kind.is_retryable else TaskState.EXHAUSTED
            available_at = None

        with self._unit_of_work() as unit_of_work:
            unit_of_work.task_store.record_outcome(
                task_id=task.task_id,
                state=state,
                now=now,
                error_code=failure.code,
                available_at=available_at,
            )

        self._observer.finished(
            task,
            state=state,
            duration_ms=_elapsed_ms(started_at),
            error_code=failure.code,
        )
        return state


def _elapsed_ms(started_at: float) -> float:
    return round((time.perf_counter() - started_at) * 1000, 2)
