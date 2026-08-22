"""The dispatcher use cases actually call.

Writes a durable row into the caller's open transaction and nothing else. No network
call, no broker handshake, no HTTP request: those all belong to whatever drains the
table later, and doing any of them here would put a fallible external dependency
inside a business transaction, which is the precise failure the outbox pattern
exists to prevent.

The consequence worth stating plainly: after ``dispatch`` returns, nothing has run
and nothing has been delivered. Work has been *promised*, atomically with the change
that justified it.
"""

from __future__ import annotations

from datetime import datetime

from learning_platform.application.ports.task_dispatcher import DispatchReceipt
from learning_platform.application.ports.task_store import TaskDispatchStore
from learning_platform.application.tasks.registry import TaskRegistry
from learning_platform.domain.clock import Clock
from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.tasks import (
    RetryPolicy,
    TaskPayload,
    TaskType,
    validate_task_payload,
)
from learning_platform.infrastructure.observability.context import current_correlation_id

__all__ = ["OutboxTaskDispatcher"]

_MAX_IDEMPOTENCY_KEY_LENGTH = 200


class OutboxTaskDispatcher:
    """Records owed work in the same transaction as the work that owes it.

    Implements ``application.ports.task_dispatcher.TaskDispatcher``.
    """

    def __init__(
        self,
        store: TaskDispatchStore,
        *,
        registry: TaskRegistry,
        clock: Clock,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._store = store
        self._registry = registry
        self._clock = clock
        self._retry_policy = retry_policy or RetryPolicy()

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
        """Record that ``task_type`` should run with ``payload``."""
        validate_task_payload(payload)

        if not self._registry.is_registered(task_type):
            # Refused at dispatch rather than discovered at drain. An unregistered
            # type would otherwise become a row that can never succeed, found only
            # when something eventually reads the failure column.
            raise InvariantViolation(
                f"task type {str(task_type)!r} has no registered handler in this deployment"
            )

        if payload_version < 1:
            raise InvariantViolation("payload versions start at one")

        if idempotency_key is not None:
            idempotency_key = idempotency_key.strip()
            if not idempotency_key:
                raise InvariantViolation("an idempotency key must not be blank")
            if len(idempotency_key) > _MAX_IDEMPOTENCY_KEY_LENGTH:
                raise InvariantViolation("the idempotency key is too long to be a stable key")

        now = self._clock.now()
        if available_at is None:
            available_at = now
        elif available_at.tzinfo is None:
            raise InvariantViolation("available_at must be timezone-aware")

        budget = self._retry_policy.max_attempts if max_attempts is None else max_attempts
        if budget < 1:
            raise InvariantViolation("a task must be allowed at least one attempt")

        task_id, deduplicated = self._store.enqueue(
            task_type=task_type,
            payload=payload,
            payload_version=payload_version,
            available_at=available_at,
            max_attempts=budget,
            idempotency_key=idempotency_key,
            # Falls back to the correlation identifier of the request in progress, so
            # a use case does not have to thread it through by hand to get a trail
            # from request to eventual execution.
            correlation_id=correlation_id or current_correlation_id(),
        )
        return DispatchReceipt(task_id=task_id, deduplicated=deduplicated)
