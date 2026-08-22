"""Which task types exist, and which code may run them.

A durable task record names its work with a string that came out of a database. The
registry is what stops that string from being able to choose code: it maps a task
type to a handler that was registered in Python, at import time, by name. There is no
dynamic import, no ``eval``, no module path in the payload, and no fallback that
tries to guess. A type nobody registered simply cannot run.

That property is the reason the drain endpoint can be safe. Even if an attacker could
write a row into the dispatch table, the worst available outcome is a task type this
deployment refuses.
"""

from __future__ import annotations

from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field

from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.identifiers import InternalId
from learning_platform.domain.tasks import (
    TaskFailed,
    TaskFailureKind,
    TaskPayload,
    TaskType,
)

__all__ = ["TaskContext", "TaskHandler", "TaskRegistration", "TaskRegistry"]


@dataclass(frozen=True, slots=True)
class TaskContext:
    """Everything a handler is given, and nothing more.

    A handler receives identifiers and delivery facts. It does not receive a database
    session, a request, a user, or an authorization decision: it loads what it needs
    and revalidates permission itself, because the work may run long after the
    request that asked for it and permissions can be revoked in between.
    """

    task_id: InternalId
    task_type: TaskType
    payload: TaskPayload
    payload_version: int
    attempt: int
    """1-based. Any attempt after the first means a previous one did not finish, so a
    handler that is not naturally idempotent can use this to check before acting."""

    max_attempts: int
    correlation_id: str | None = None


type TaskHandler = Callable[[TaskContext], None]
"""Does the work, or raises.

Returning normally means the work is done and must not be repeated. Raising
:class:`~learning_platform.domain.tasks.TaskFailed` classifies the failure; raising
anything else is treated as a retryable infrastructure fault.

Handlers must be idempotent. Delivery is at-least-once under every runtime ADR 0004
considered, so a handler will eventually run twice for one dispatch.
"""


@dataclass(frozen=True, slots=True)
class TaskRegistration:
    """One task type, its handler, and the payload versions it understands."""

    task_type: TaskType
    handler: TaskHandler
    payload_versions: frozenset[int] = field(default_factory=lambda: frozenset({1}))


class TaskRegistry:
    """The controlled vocabulary of task types."""

    def __init__(self) -> None:
        self._registrations: dict[str, TaskRegistration] = {}

    def register(
        self,
        task_type: TaskType,
        handler: TaskHandler,
        *,
        payload_versions: Iterable[int] = (1,),
    ) -> None:
        """Bind a handler to a task type.

        Args:
            payload_versions: every payload schema version this handler can read.
                A handler keeps accepting an old version until no rows carrying it
                remain, which is what lets a deployment roll out without stranding
                work that was dispatched by the previous one.

        Raises:
            InvariantViolation: if the type is already registered, or if no payload
                version is declared.

        Re-registration is refused rather than allowed to overwrite. Overwriting would
        make which handler runs depend on module import order, which is a property no
        one should have to reason about while investigating why the wrong code ran.
        """
        versions = frozenset(payload_versions)
        if not versions:
            raise InvariantViolation(
                f"task type {task_type!r} must declare at least one payload version"
            )
        if any(version < 1 for version in versions):
            raise InvariantViolation("payload versions start at one")
        if task_type in self._registrations:
            raise InvariantViolation(f"task type {task_type!r} is already registered")

        self._registrations[task_type] = TaskRegistration(
            task_type=task_type, handler=handler, payload_versions=versions
        )

    def is_registered(self, task_type: TaskType) -> bool:
        """Whether this deployment knows how to run ``task_type``."""
        return task_type in self._registrations

    def registrations(self) -> Mapping[str, TaskRegistration]:
        """Every registration, for diagnostics. Read-only."""
        return dict(self._registrations)

    def resolve(self, task_type: TaskType, payload_version: int) -> TaskHandler:
        """Return the handler for a stored task record.

        Raises:
            TaskFailed: with :attr:`TaskFailureKind.INVALID_PAYLOAD` if the type is
                unknown or the payload version is not supported.

        A stored row naming a type this deployment does not have is a real situation,
        not a bug to crash on: a rollback to an earlier build, or a task removed in a
        later one, both produce it. It is a terminal failure rather than a retryable
        one, because retrying the same row against the same code cannot succeed. The
        row keeps its payload, so redeploying the handler and resetting the row is a
        deliberate operator action rather than a lost record.
        """
        registration = self._registrations.get(task_type)
        if registration is None:
            raise TaskFailed(TaskFailureKind.INVALID_PAYLOAD, "unknown_task_type")
        if payload_version not in registration.payload_versions:
            raise TaskFailed(TaskFailureKind.INVALID_PAYLOAD, "unsupported_payload_version")
        return registration.handler
