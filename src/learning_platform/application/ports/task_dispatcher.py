"""Requesting background work.

This is the whole surface application code sees. A use case says what should happen
later; it does not know, and must not be able to discover, whether that becomes a row
drained by a scheduled invocation, a message on a managed queue, or a handler run
inline in a test. ADR 0004 chose the first and left the others swappable, and this
port is what makes that swap a configuration change rather than an edit to every
call site.

Nothing here mentions a queue URL, a topic, a project, an endpoint, a cron
expression, or a vendor message ID. If any of those ever appear in this file, the
abstraction has failed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Protocol, runtime_checkable

from learning_platform.domain.identifiers import InternalId
from learning_platform.domain.tasks import TaskPayload, TaskType

__all__ = ["DispatchReceipt", "TaskDispatcher"]


@dataclass(frozen=True, slots=True)
class DispatchReceipt:
    """The outcome of asking for work to happen later."""

    task_id: InternalId
    """Identifies the durable record, so a caller can log or audit what it asked for."""

    deduplicated: bool = False
    """True when an identical ``idempotency_key`` was already recorded, so this call
    adopted the existing request rather than creating a second one.

    Not an error. A use case that runs twice because a request was retried should
    produce one piece of background work, and should not have to know it was the
    second caller.
    """


@runtime_checkable
class TaskDispatcher(Protocol):
    """Records that work is owed."""

    def dispatch(
        self,
        task_type: TaskType,
        payload: TaskPayload,
        *,
        payload_version: int = 1,
        idempotency_key: str | None = None,
        available_at: datetime | None = None,
        correlation_id: str | None = None,
        max_attempts: int | None = None,
    ) -> DispatchReceipt:
        """Record that ``task_type`` should run with ``payload``.

        Args:
            task_type: a registered task type. Dispatching an unregistered type is
                refused, so a typo becomes an immediate error rather than work that
                is stored forever and never run.
            payload: internal identifiers and scalars. Never entity graphs, secrets,
                tokens, or message plaintext: this is written to durable storage.
            payload_version: the schema version of ``payload``. Stored alongside it so
                a later deployment can tell what shape an old row is in, instead of
                guessing.
            idempotency_key: a stable key derived from the business fact that
                justifies the work, such as "sync course X to revision Y". Dispatching
                twice with one key records the work once.
            available_at: the earliest time the task may run. Defaults to immediately.
            correlation_id: ties the eventual execution back to the request that
                caused it.
            max_attempts: overrides the configured retry budget for this task.

        Returns:
            A receipt identifying the durable record.

        Raises:
            InvariantViolation: if the payload or task type is not acceptable.

        Returns once the work is *recorded*, not once it is done, and not once any
        delivery system has acknowledged it. Callers must not depend on completion,
        on ordering between dispatches, or on the task running exactly once: delivery
        is at-least-once by design, so handlers are idempotent.

        Under ADR 0004 the recording participates in the caller's transaction. Work
        is owed only if the business change that justified it committed, and a
        rollback leaves no trace of either.
        """
        ...
