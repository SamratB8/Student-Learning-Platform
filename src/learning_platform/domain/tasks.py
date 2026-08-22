"""Background work as a domain concept: what it is, and what may happen to it.

A dispatched task is a promise the platform made to itself inside a transaction:
"this business change happened, and this follow-up work is owed." ADR 0004 makes the
database record of that promise authoritative, so the rules about what a task is and
how its state may change belong here, framework-free, rather than in whatever
delivery mechanism happens to be selected.

Nothing in this module knows about PostgreSQL, HTTP, cron, or a queue. It defines:

* what a task type and payload are allowed to be,
* which state transitions are legal,
* how a failure is classified, and
* when a retry becomes due.

Delivery is somebody else's problem, deliberately.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from typing import Final

from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.sensitive import is_sensitive_key

__all__ = [
    "MAX_PAYLOAD_ENTRIES",
    "RetryPolicy",
    "TaskFailed",
    "TaskFailureKind",
    "TaskPayload",
    "TaskState",
    "TaskType",
    "ensure_transition",
    "validate_error_code",
    "validate_task_payload",
]

# A dotted lowercase identifier such as ``classroom.sync_course``. Constrained so a
# task type stays a controlled vocabulary entry rather than becoming a Python import
# path, a callable name, or anything else that could turn a database row into a
# choice of code to execute.
_TASK_TYPE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

_ERROR_CODE_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]{0,62}$")

MAX_PAYLOAD_ENTRIES: Final = 32
"""A payload carries identifiers, not documents. The bound is a design statement."""

_MAX_PAYLOAD_STRING_LENGTH: Final = 512


type TaskPayload = Mapping[str, str | int | float | bool | None]
"""Scalars only, keyed by name.

Deliberately not a recursive JSON type. A payload that needs nesting is carrying an
entity graph, and an entity graph in a queue is a stale copy of the database by the
time it is read. Pass internal identifiers and let the handler load what it needs,
under the authorization rules that apply when it actually runs.
"""


class TaskType(str):
    """A controlled task-type identifier, such as ``classroom.sync_course``."""

    __slots__ = ()

    def __new__(cls, value: str) -> TaskType:
        if not _TASK_TYPE_PATTERN.match(value):
            raise InvariantViolation(
                "task type must be a dotted lowercase name such as 'classroom.sync_course'"
            )
        return super().__new__(cls, value)


class TaskState(StrEnum):
    """Where a dispatched task has got to.

    The set is deliberately small. An earlier sketch separated "handed to the
    runtime" from "currently executing", but under ADR 0004 a claimed row is exactly
    both of those at once and nothing can observe the difference: the claim is what
    hands the work over, and the lease is what proves something is still working on
    it. A state the system cannot distinguish is a state that will eventually lie.
    """

    PENDING = "pending"
    """Owed, and eligible to run once ``available_at`` has passed."""

    CLAIMED = "claimed"
    """Leased by a runner. Returns to :attr:`PENDING` if the lease expires, which is
    how work abandoned by a killed invocation recovers itself."""

    SUCCEEDED = "succeeded"
    """The handler completed. Terminal."""

    FAILED = "failed"
    """Refused without retrying: the payload, its version, or the task type cannot be
    handled by this code, so trying again would fail identically. Terminal."""

    EXHAUSTED = "exhausted"
    """Retried up to ``max_attempts`` and still failing. Terminal, and the state an
    operator should be alerted on, because it means work was genuinely lost rather
    than merely refused."""

    CANCELLED = "cancelled"
    """Withdrawn before it ran, because the business reason for it no longer holds.
    Terminal."""

    @property
    def is_terminal(self) -> bool:
        """Whether no further transition is possible."""
        return self in _TERMINAL_STATES


_TERMINAL_STATES: Final[frozenset[TaskState]] = frozenset(
    {
        TaskState.SUCCEEDED,
        TaskState.FAILED,
        TaskState.EXHAUSTED,
        TaskState.CANCELLED,
    }
)

ALLOWED_TRANSITIONS: Final[Mapping[TaskState, frozenset[TaskState]]] = {
    TaskState.PENDING: frozenset({TaskState.CLAIMED, TaskState.CANCELLED}),
    # Back to PENDING is a retry, or a lease that expired and was reclaimed.
    TaskState.CLAIMED: frozenset(
        {
            TaskState.PENDING,
            TaskState.SUCCEEDED,
            TaskState.FAILED,
            TaskState.EXHAUSTED,
            TaskState.CANCELLED,
        }
    ),
    TaskState.SUCCEEDED: frozenset(),
    TaskState.FAILED: frozenset(),
    TaskState.EXHAUSTED: frozenset(),
    TaskState.CANCELLED: frozenset(),
}


def ensure_transition(current: TaskState, target: TaskState) -> None:
    """Permit a state change, or refuse it.

    Raises:
        InvariantViolation: if the transition is not legal.

    Reaching a terminal state twice is refused rather than tolerated. At-least-once
    delivery means a duplicate *delivery* is expected and must be safe, but a
    duplicate *completion* means two runners believed they owned the same row, and
    silently accepting that would hide the bug that caused it.
    """
    if target not in ALLOWED_TRANSITIONS[current]:
        raise InvariantViolation(
            f"a task in state {current.value!r} may not move to {target.value!r}"
        )


class TaskFailureKind(StrEnum):
    """Why a task failed, and therefore whether trying again could help."""

    INFRASTRUCTURE = "infrastructure"
    """The database, network, or runtime misbehaved. Retryable."""

    PROVIDER = "provider"
    """An external provider failed, timed out, or rate-limited us. Retryable, and the
    reason retries are bounded and spaced rather than immediate."""

    INVALID_PAYLOAD = "invalid_payload"
    """The payload, or its schema version, cannot be interpreted by this code. Not
    retryable: the same bytes would fail the same way on every attempt."""

    AUTHORIZATION_INVALIDATED = "authorization_invalidated"
    """The permission that justified this work no longer holds. Not retryable, and
    never silently ignored.

    SECURITY_MODEL.md denies by default and requires server-side evaluation. A task
    may sit in the queue for a long time, during which a grant can be revoked, a
    membership can end, or an account can be suspended, so a handler that acts on
    user-scoped content revalidates authorization at execution time instead of
    trusting the decision made when the work was dispatched.
    """

    @property
    def is_retryable(self) -> bool:
        return self in {TaskFailureKind.INFRASTRUCTURE, TaskFailureKind.PROVIDER}


class TaskFailed(Exception):
    """Raised by a handler to classify its own failure.

    Not a :class:`~learning_platform.domain.errors.DomainError`: those carry a
    user-facing message and reach HTTP responses, and this never does. A task failure
    is an operational fact reported to the runner.

    ``code`` is a short stable slug for the failure, persisted so an operator can
    group failures without the platform storing an exception message. Messages and
    tracebacks are not persisted, because they routinely quote the values that caused
    them and a task payload sits next to them in the same row.
    """

    def __init__(self, kind: TaskFailureKind, code: str) -> None:
        self.kind = kind
        self.code = validate_error_code(code)
        super().__init__(f"task failed: {self.kind.value}/{self.code}")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """How long to wait before a failed task becomes eligible again.

    Exponential, capped, and bounded by ``max_attempts``. No jitter: a single drain
    claims a batch and works through it in order, so there is no fleet of workers to
    de-synchronise, and adding randomness would only make tests need a random source.
    Revisit if delivery ever becomes concurrent across many runners.
    """

    max_attempts: int = 5
    base_delay_seconds: int = 30
    max_delay_seconds: int = 3600

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise InvariantViolation("a retry policy must permit at least one attempt")
        if self.base_delay_seconds < 1:
            raise InvariantViolation("retry backoff must be at least one second")
        if self.max_delay_seconds < self.base_delay_seconds:
            raise InvariantViolation("the retry cap must not be below the base delay")

    def next_attempt_at(self, *, attempt: int, now: datetime) -> datetime:
        """When a task that has just failed its ``attempt``-th try may run again.

        ``attempt`` is 1-based, so the first failure waits ``base_delay_seconds``.
        """
        if attempt < 1:
            raise InvariantViolation("attempt numbering starts at one")
        # Shift rather than pow, and clamp the exponent, so a pathological attempt
        # count cannot build an enormous integer before the cap is applied.
        exponent = min(attempt - 1, 32)
        delay = min(self.base_delay_seconds << exponent, self.max_delay_seconds)
        return now + timedelta(seconds=delay)

    def has_attempts_remaining(self, *, attempt: int, max_attempts: int | None = None) -> bool:
        """Whether another try is permitted after ``attempt`` has failed.

        ``max_attempts`` overrides the policy default with the budget recorded on the
        task itself, so a dispatch that asked for a different number of tries keeps
        it even if the deployment's configured default changes afterwards.
        """
        budget = self.max_attempts if max_attempts is None else max_attempts
        return attempt < budget


def validate_error_code(code: str) -> str:
    """Return a failure code, or refuse it.

    Raises:
        InvariantViolation: if the code is not a short lowercase slug.

    Constrained so that persisting a failure cannot become a way to persist an
    exception message, a stack frame, or a rejected value.
    """
    normalized = code.strip().lower()
    if not _ERROR_CODE_PATTERN.match(normalized):
        raise InvariantViolation(
            "a task error code must be a short lowercase slug such as 'provider_timeout'"
        )
    return normalized


def validate_task_payload(payload: TaskPayload) -> None:
    """Refuse a payload that must not be written down or cross a process boundary.

    Raises:
        InvariantViolation: if a field name looks sensitive, if the payload is too
            large to be a set of identifiers, or if a value is not a scalar.

    The sensitive-name check is a guard rail, not a security boundary: it catches the
    accident of forwarding a token into durable storage, and cannot detect a secret
    hidden under an innocuous name. The rule that payloads carry internal identifiers
    only is what actually keeps secrets out, and this is what makes breaking that
    rule noisy.
    """
    if len(payload) > MAX_PAYLOAD_ENTRIES:
        raise InvariantViolation(
            f"a task payload may carry at most {MAX_PAYLOAD_ENTRIES} fields; "
            "pass identifiers rather than records"
        )
    for key, value in payload.items():
        if not key or not isinstance(key, str):
            raise InvariantViolation("task payload field names must be non-empty strings")
        if is_sensitive_key(key):
            raise InvariantViolation(f"task payload may not carry the sensitive field {key!r}")
        # bool before int: bool is a subclass of int and would otherwise pass silently
        # under a check that only named int.
        if not isinstance(value, str | int | float | bool | None):
            raise InvariantViolation(
                f"task payload field {key!r} must be a scalar; pass an identifier "
                "instead of an object"
            )
        if isinstance(value, str) and len(value) > _MAX_PAYLOAD_STRING_LENGTH:
            raise InvariantViolation(f"task payload field {key!r} is too long to be an identifier")
