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
from learning_platform.application.ports.task_dispatcher import TaskDispatcher
from learning_platform.application.ports.task_store import TaskDispatchStore
from learning_platform.application.tasks.registry import TaskRegistry
from learning_platform.domain.clock import Clock, SystemClock
from learning_platform.domain.tasks import RetryPolicy

__all__ = ["SqlAlchemyUnitOfWork", "UnitOfWorkFactory"]


class SqlAlchemyUnitOfWork:
    """A transaction, plus the repositories bound to it."""

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        task_registry: TaskRegistry | None = None,
        clock: Clock | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._session: Session | None = None
        self._task_registry = task_registry
        self._clock = clock or SystemClock()
        self._retry_policy = retry_policy or RetryPolicy()

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

    @property
    def task_store(self) -> TaskDispatchStore:
        """The dispatch store bound to this transaction.

        Imported lazily for the same reason as the audit sink: the store needs the
        session this class owns.
        """
        from learning_platform.infrastructure.tasks.repository import (
            SqlAlchemyTaskDispatchStore,
        )

        return SqlAlchemyTaskDispatchStore(self.session)

    @property
    def tasks(self) -> TaskDispatcher:
        """Dispatch background work inside this transaction.

        Raises:
            RuntimeError: if the factory was built without a task registry, because
                dispatching against an empty registry would refuse every task type
                and the reason would be far from the call site.

        This is the outbox in practice: ``uow.tasks.dispatch(...)`` alongside the
        business writes means both land, or neither does.
        """
        if self._task_registry is None:
            raise RuntimeError("no task registry is configured for this unit of work")

        from learning_platform.infrastructure.tasks.outbox import OutboxTaskDispatcher

        return OutboxTaskDispatcher(
            self.task_store,
            registry=self._task_registry,
            clock=self._clock,
            retry_policy=self._retry_policy,
        )

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

    def __init__(
        self,
        engine: Engine,
        *,
        task_registry: TaskRegistry | None = None,
        clock: Clock | None = None,
        retry_policy: RetryPolicy | None = None,
    ) -> None:
        self._task_registry = task_registry
        self._clock = clock
        self._retry_policy = retry_policy
        self._session_factory = sessionmaker(
            bind=engine,
            # Attribute access after commit would emit a query against a closed
            # transaction, so state is read before the boundary, deliberately.
            expire_on_commit=False,
            autoflush=True,
        )

    def __call__(self) -> SqlAlchemyUnitOfWork:
        return SqlAlchemyUnitOfWork(
            self._session_factory,
            task_registry=self._task_registry,
            clock=self._clock,
            retry_policy=self._retry_policy,
        )
