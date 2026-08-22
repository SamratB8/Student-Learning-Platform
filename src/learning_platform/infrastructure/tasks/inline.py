"""Inline dispatch: runs the handler immediately, in the caller.

This exists for tests and for local experimentation, and it refuses to exist anywhere
else. Constructing it in a deployed environment raises, rather than logging a warning
and carrying on, because the failure it prevents is silent: inline execution ties a
user's request to the task's latency, offers no retry, has no durable record, and
loses everything in flight when the process ends. A deployment that quietly fell back
to it would look like it was working right up until work started disappearing.

That guard mirrors the hosted-environment rule in ``infrastructure/config/hosting.py``
and exists for the same reason: the weakest behaviour must not also be the quietest.

Inline dispatch is not the outbox. It does not participate in a transaction, so work
dispatched inside a use case that later rolls back has already happened.
"""

from __future__ import annotations

from datetime import datetime

from learning_platform.application.ports.task_dispatcher import DispatchReceipt
from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.domain.errors import ConfigurationError
from learning_platform.domain.identifiers import InternalId, new_internal_id
from learning_platform.domain.tasks import (
    TaskPayload,
    TaskType,
    validate_task_payload,
)
from learning_platform.infrastructure.config.environments import AppEnvironment
from learning_platform.infrastructure.observability.logging import get_logger

__all__ = ["InlineTaskDispatcher"]

_logger = get_logger(__name__)


class InlineTaskDispatcher:
    """Executes registered handlers synchronously, in development and tests only.

    Implements ``application.ports.task_dispatcher.TaskDispatcher``.
    """

    def __init__(
        self,
        registry: TaskRegistry,
        *,
        environment: AppEnvironment = AppEnvironment.TEST,
    ) -> None:
        """
        Args:
            environment: the environment this dispatcher would run in.

        Raises:
            ConfigurationError: if ``environment`` is a deployed one. Required rather
                than defaulted to permissive, so selecting inline execution in
                staging or production is impossible rather than merely discouraged.
        """
        if environment.is_deployed:
            raise ConfigurationError(
                "inline task dispatch runs work inside the request that asked for it, "
                "with no durability and no retry, and is refused in a deployed "
                "environment. Use the durable dispatcher (ADR 0004)."
            )
        self._registry = registry
        self._environment = environment
        self._seen_keys: set[str] = set()

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
        """Run the handler for ``task_type`` immediately.

        ``available_at`` is honoured only in the sense that it is ignored: there is no
        scheduler here, so a delayed task runs now. That difference from the durable
        dispatcher is why this is unsuitable for anything but a test.

        A repeated ``idempotency_key`` is dropped without running the handler,
        matching the durable dispatcher closely enough that a test can exercise the
        deduplicating branch of a use case.
        """
        validate_task_payload(payload)
        task_id = new_internal_id()

        if idempotency_key is not None:
            if idempotency_key in self._seen_keys:
                return DispatchReceipt(task_id=task_id, deduplicated=True)
            self._seen_keys.add(idempotency_key)

        handler = self._registry.resolve(task_type, payload_version)

        _logger.info("task.started", task_id=str(task_id), task_type=str(task_type), attempt=1)
        try:
            handler(
                TaskContext(
                    task_id=task_id,
                    task_type=task_type,
                    payload=payload,
                    payload_version=payload_version,
                    attempt=1,
                    max_attempts=max_attempts or 1,
                    correlation_id=correlation_id,
                )
            )
        except Exception:
            # Re-raised, not recorded. There is no durable row to mark failed and no
            # retry to schedule, so the caller must see the failure or it is lost.
            _logger.exception("task.failed", task_id=str(task_id), task_type=str(task_type))
            raise

        _logger.info("task.finished", task_id=str(task_id), task_type=str(task_type))
        return DispatchReceipt(task_id=InternalId(task_id), deduplicated=False)
