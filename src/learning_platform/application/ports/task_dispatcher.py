"""Background work dispatch.

ADR 0002 removed the assumption of a colocated always-running worker; ADR 0004 owns
the runtime choice and is still open. This port exists so application code can
express "this happens later" without importing a queue client, and so the runtime
can be chosen without rewriting call sites.

Constraints accepted in ADR 0004 and enforced here:

* A task is a stable name plus a JSON-serializable payload of internal identifiers.
  Never entity graphs, secrets, tokens, or message plaintext, because a payload is
  written to durable storage and crosses a process boundary.
* Handlers are idempotent. Every plausible runtime retries.
* Dispatch happens after the transaction that justifies it commits. Provider-facing
  work uses the outbox instead.
* A task must not assume it runs in the same process, host, or region as its caller.
"""

from __future__ import annotations

import re
from typing import Final, Protocol, runtime_checkable

from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.sensitive import is_sensitive_key

__all__ = ["TaskDispatcher", "TaskName", "TaskPayload", "validate_task_payload"]

type TaskPayload = dict[str, str | int | float | bool | None]

_TASK_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")


class TaskName(str):
    """A dotted lowercase task name, such as ``classroom.sync_course``."""

    __slots__ = ()

    def __new__(cls, value: str) -> TaskName:
        if not _TASK_NAME_PATTERN.match(value):
            raise InvariantViolation(
                "task name must be a dotted lowercase name such as 'classroom.sync_course'"
            )
        return super().__new__(cls, value)


def validate_task_payload(payload: TaskPayload) -> None:
    """Reject a payload that must not cross a process boundary.

    Raises:
        InvariantViolation: if a field name looks sensitive.

    This is a guard rail, not a security boundary. It catches the accident of
    forwarding a token into a queue; it cannot detect a secret hidden under an
    innocuous name.
    """
    for key in payload:
        if is_sensitive_key(key):
            raise InvariantViolation(f"task payload may not carry the sensitive field {key!r}")


@runtime_checkable
class TaskDispatcher(Protocol):
    """Hands work to whatever executes it."""

    def dispatch(self, name: TaskName, payload: TaskPayload) -> None:
        """Request that ``name`` runs with ``payload``.

        Returns once the request is accepted, not once the work is done. Callers must
        not depend on completion, on ordering between dispatches, or on the task
        running exactly once.
        """
        ...
