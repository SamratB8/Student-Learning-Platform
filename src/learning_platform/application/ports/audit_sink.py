"""Where audit events go.

An audit event is written inside the same unit of work as the action it describes,
so a committed change always has its record and a rolled-back attempt leaves none.
Auditing an attempt that never happened is as wrong as failing to audit one that did.

A denied or failed action is still audited. Refusals are precisely the events worth
keeping.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from learning_platform.domain.audit import AuditEvent

__all__ = ["AuditSink"]


@runtime_checkable
class AuditSink(Protocol):
    """Accepts audit events for durable, append-oriented storage."""

    def record(self, event: AuditEvent) -> None:
        """Stage one audit event for writing.

        Implementations write within the caller's transaction and must not commit on
        their own; the unit of work decides. Implementations must not mutate or
        enrich the event, because what is stored has to be what the caller asserted.
        """
        ...
