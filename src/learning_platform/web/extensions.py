"""The application's constructed dependencies.

Flask extensions are usually module-level singletons initialised against an app.
That pattern does not survive two applications in one process, which happens in
tests, and it hides what a request actually depends on.

Instead the factory builds one :class:`PlatformExtensions` and stores it on the app.
Handlers ask for it explicitly. Everything here is constructed once per application,
never per request, and holds no request-scoped state.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Final

from flask import Flask, current_app

from learning_platform.application.tasks.runner import TaskRunner
from learning_platform.domain.clock import Clock, SystemClock
from learning_platform.domain.tasks import RetryPolicy
from learning_platform.infrastructure.config.settings import Settings
from learning_platform.infrastructure.database.engine import build_engine, dispose_engine
from learning_platform.infrastructure.database.unit_of_work import UnitOfWorkFactory
from learning_platform.infrastructure.tasks.observer import LoggingTaskObserver
from learning_platform.worker import build_task_registry

if TYPE_CHECKING:
    from sqlalchemy import Engine

__all__ = ["EXTENSION_KEY", "PlatformExtensions", "get_extensions"]

EXTENSION_KEY: Final = "learning_platform"


class PlatformExtensions:
    """Application-scoped dependencies."""

    def __init__(self, settings: Settings, *, clock: Clock | None = None) -> None:
        self.settings = settings
        self.clock: Clock = clock or SystemClock()

        # The set of task types this deployment can run, fixed at composition. A row
        # naming anything else cannot select code (ADR 0004).
        self.task_registry = build_task_registry()
        self.retry_policy = RetryPolicy(max_attempts=settings.task_max_attempts)

        self._engine: Engine | None = None
        self._unit_of_work_factory: UnitOfWorkFactory | None = None
        self._task_runner: TaskRunner | None = None

        if settings.database_configured:
            # Constructing an engine opens no connection, so this is safe even when
            # PostgreSQL is not running.
            self._engine = build_engine(settings)
            self._unit_of_work_factory = UnitOfWorkFactory(
                self._engine,
                task_registry=self.task_registry,
                clock=self.clock,
                retry_policy=self.retry_policy,
            )
            # Background execution needs durable storage by definition, so there is
            # no runner without a database. There is deliberately no in-memory
            # fallback: work that cannot be recorded must not appear to have been
            # accepted.
            self._task_runner = TaskRunner(
                unit_of_work=self._unit_of_work_factory,
                registry=self.task_registry,
                clock=self.clock,
                retry_policy=self.retry_policy,
                lease_seconds=settings.task_lease_seconds,
                batch_limit=settings.task_drain_batch_limit,
                observer=LoggingTaskObserver(),
            )

    @property
    def database_available(self) -> bool:
        """Whether a database was configured. Not whether it is reachable."""
        return self._engine is not None

    @property
    def engine(self) -> Engine:
        """The SQLAlchemy engine.

        Raises:
            RuntimeError: if no database is configured, so a feature that needs
                persistence fails clearly instead of silently doing nothing.
        """
        if self._engine is None:
            raise RuntimeError("no database is configured for this application")
        return self._engine

    @property
    def unit_of_work(self) -> UnitOfWorkFactory:
        """Factory for transaction boundaries.

        Raises:
            RuntimeError: if no database is configured.
        """
        if self._unit_of_work_factory is None:
            raise RuntimeError("no database is configured for this application")
        return self._unit_of_work_factory

    @property
    def task_runner(self) -> TaskRunner:
        """Runs background work that is due.

        Raises:
            RuntimeError: if no database is configured, since durable dispatch has
                nowhere to live.
        """
        if self._task_runner is None:
            raise RuntimeError("no database is configured for this application")
        return self._task_runner

    def shutdown(self) -> None:
        """Release pooled connections. Called when an application is discarded."""
        if self._engine is not None:
            dispose_engine(self._engine)


def get_extensions(app: Flask | None = None) -> PlatformExtensions:
    """Return the extensions bound to ``app``, or to the current application."""
    target = app or current_app
    extensions: PlatformExtensions = target.extensions[EXTENSION_KEY]
    return extensions
