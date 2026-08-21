"""SQLAlchemy implementation of the unit-of-work port.

One unit of work wraps one database transaction. Entering begins it, leaving cleanly
commits, and leaving with an exception rolls back. Nothing else in the codebase calls
``commit``: that is what keeps transaction boundaries in application use cases rather
than scattered through models and request handlers.
"""

from __future__ import annotations

from types import TracebackType
from typing import Self

from sqlalchemy import Engine
from sqlalchemy.orm import Session, sessionmaker

from learning_platform.application.ports.audit_sink import AuditSink

__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWorkFactory"]


class SqlAlchemyUnitOfWork:
    """A transaction, plus the repositories bound to it."""

    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None

    @property
    def session(self) -> Session:
        """The active session.

        Raises:
            RuntimeError: if accessed outside the context manager, which would mean
                work was being done without a transaction boundary.
        """
        if self._session is None:
            raise RuntimeError("unit of work is not active; use it as a context manager")
        return self._session

    @property
    def audit(self) -> AuditSink:
        """The audit sink bound to this transaction.

        Imported lazily to keep this module free of a cycle: the sink needs the
        session that this class owns.
        """
        from learning_platform.infrastructure.audit.sink import SqlAlchemyAuditSink

        return SqlAlchemyAuditSink(self.session)

    def __enter__(self) -> Self:
        self._session = self._session_factory()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        session = self._session
        if session is None:  # pragma: no cover - defensive
            return
        try:
            if exc_type is None:
                session.commit()
            else:
                session.rollback()
        finally:
            session.close()
            self._session = None
        # Returns None, so an exception always propagates. A unit of work must never
        # swallow the failure that caused its own rollback.

    def commit(self) -> None:
        """Commit early, when a use case genuinely needs a checkpoint."""
        self.session.commit()

    def rollback(self) -> None:
        """Discard everything written so far in this unit of work."""
        self.session.rollback()


class UnitOfWorkFactory:
    """Creates units of work from one engine.

    Held on the application so a request handler asks for a transaction rather than
    reaching for a global session.
    """

    def __init__(self, engine: Engine) -> None:
        self._session_factory = sessionmaker(
            bind=engine,
            # Attribute access after commit would emit a query against a closed
            # transaction, so state is read before the boundary, deliberately.
            expire_on_commit=False,
            autoflush=True,
        )

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(self._session_factory)
