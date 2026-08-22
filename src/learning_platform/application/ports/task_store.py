"""Durable storage for dispatched work.

Separate from :mod:`~learning_platform.application.ports.task_dispatcher` because the
two have different audiences. A use case dispatches and never reads back; only the
runner claims, executes, and records outcomes. Keeping them apart means application
code cannot accidentally reach into the queue's internals, and a test double for one
does not have to implement the other.

The store owns durability and atomic claiming. It does not decide policy: whether a
failure is retryable, and when a retry is due, are domain questions answered before
the store is told what to write.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from learning_platform.domain.identifiers import InternalId
from learning_platform.domain.tasks import TaskPayload, TaskState, TaskType

__all__ = ["ClaimedTask", "TaskDispatchStore"]


@dataclass(frozen=True, slots=True)
class ClaimedTask:
    """One task leased to a runner, with everything needed to execute it.

    Carries no lease token. The lease is a deadline stored on the row, not a
    capability held by the runner, so a runner that has lost its lease cannot record
    an outcome for a row another runner has since claimed: the state transition check
    refuses it.
    """

    task_id: InternalId
    task_type: TaskType
    payload_version: int
    payload: TaskPayload
    attempt: int
    """1-based, and already incremented by the claim. The first execution is
    attempt 1, so a handler reading this sees the try it is currently on."""

    max_attempts: int
    correlation_id: str | None = None


@runtime_checkable
class TaskDispatchStore(Protocol):
    """Persists dispatched work and hands it out for execution."""

    def enqueue(
        self,
        *,
        task_type: TaskType,
        payload: TaskPayload,
        payload_version: int,
        available_at: datetime,
        max_attempts: int,
        idempotency_key: str | None,
        correlation_id: str | None,
    ) -> tuple[InternalId, bool]:
        """Record owed work, returning its identifier and whether it was a duplicate.

        Writes into the caller's open transaction and does not commit. That is the
        entire point of the outbox: the work is recorded if and only if the business
        change that justified it is.

        A repeated ``idempotency_key`` records nothing new and returns the existing
        identifier with ``True``. It is not an error, and it must not abort the
        caller's transaction, because the caller is usually a retried request that
        has no idea it is the second one.
        """
        ...

    def claim_due(self, *, now: datetime, limit: int, lease_seconds: int) -> Sequence[ClaimedTask]:
        """Lease up to ``limit`` tasks that are ready to run.

        A task is ready when it is ``PENDING`` and ``available_at`` has passed, or
        when it is ``CLAIMED`` and its lease has expired. The second case is the
        recovery path: an invocation killed mid-task leaves a row claimed forever
        otherwise, and no separate reaper is needed to notice.

        Claiming increments the attempt counter and extends a lease, and must be
        atomic against other runners. Two concurrent drains may never receive the
        same task.
        """
        ...

    def record_outcome(
        self,
        *,
        task_id: InternalId,
        state: TaskState,
        now: datetime,
        error_code: str | None = None,
        available_at: datetime | None = None,
    ) -> None:
        """Move a task to ``state``.

        Args:
            state: the new state, already decided from domain rules.
            error_code: a short slug. Never an exception message or traceback.
            available_at: when a retried task becomes eligible again. Required when
                returning a task to ``PENDING``, meaningless otherwise.

        Raises:
            InvariantViolation: if the transition is not legal from the task's
                current state.
            NotFound: if no such task exists.
        """
        ...
