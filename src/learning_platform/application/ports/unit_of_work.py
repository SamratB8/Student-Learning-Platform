"""Transaction boundary.

ADR 0001: commits belong to application use cases, not to model ``save()`` helpers.
A use case opens exactly one unit of work, does its work, and lets the context
manager commit on success or roll back on any exception.

Repositories are obtained from the unit of work rather than injected separately, so
it is impossible to hold a repository that is not bound to the current transaction.
"""

from __future__ import annotations

from types import TracebackType
from typing import Protocol, Self, runtime_checkable

__all__ = ["UnitOfWork"]


@runtime_checkable
class UnitOfWork(Protocol):
    """A single atomic unit of work.

    Leaving the context manager without an exception commits. Leaving it with an
    exception rolls back. There is no partial-success mode: a use case that needs
    two independent outcomes needs two units of work, and must say why.
    """

    def __enter__(self) -> Self:
        """Begin the transaction."""
        ...

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> bool | None:
        """Commit on clean exit, roll back otherwise. Never suppresses an exception."""
        ...

    def commit(self) -> None:
        """Commit early, when a use case genuinely needs a checkpoint."""
        ...

    def rollback(self) -> None:
        """Discard everything written in this unit of work."""
        ...
