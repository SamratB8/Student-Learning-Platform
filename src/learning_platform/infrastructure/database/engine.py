"""Engine construction and connectivity checks.

ADR 0002 puts the web application on a serverless runtime, so a process is
short-lived and may handle few requests. Pooling is therefore configured for many
small, short-lived pools rather than one large long-lived one, and connections are
checked before use because an idle connection may have been closed by a managed
database or a connection pooler between invocations.
"""

from __future__ import annotations

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.exc import SQLAlchemyError

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.settings import Settings

__all__ = ["build_engine", "check_connection", "dispose_engine"]


def build_engine(settings: Settings) -> Engine:
    """Create the SQLAlchemy engine.

    Raises:
        ConfigurationError: if no database URL is configured.

    Creating an engine does not open a connection, so this succeeds even when the
    database is unreachable. Use :func:`check_connection` to test reachability.
    """
    if not settings.database_configured:
        raise ConfigurationError("DATABASE_URL is not configured")

    return create_engine(
        settings.database_url.get_secret_value(),
        pool_size=settings.database_pool_size,
        max_overflow=0,
        pool_timeout=settings.database_pool_timeout_seconds,
        # Recycle well inside the idle timeout typical of managed PostgreSQL.
        pool_recycle=300,
        # Cheap liveness check on checkout. Worth one round trip to avoid surfacing a
        # stale-connection error as a request failure.
        pool_pre_ping=True,
        # Never log SQL. Statements and bound parameters contain personal data.
        echo=False,
        echo_pool=False,
        future=True,
        connect_args={
            # Bounds how long a new connection may take to establish. Without it an
            # unreachable host can block for minutes, because a dropped SYN is
            # retried rather than refused.
            "connect_timeout": settings.database_connect_timeout_seconds,
            # Identifies the application in pg_stat_activity, which makes it possible
            # to tell platform connections from a migration run or a manual session.
            "application_name": f"learning-platform-{settings.app_env.value}",
        },
    )


def check_connection(engine: Engine) -> bool:
    """Return whether the database currently answers a trivial query.

    Used by the readiness endpoint. Returns a boolean rather than raising, because
    "not ready" is an expected state, not an error.
    """
    try:
        with engine.connect() as connection:
            connection.execute(text("SELECT 1"))
    except SQLAlchemyError:
        return False
    return True


def dispose_engine(engine: Engine) -> None:
    """Close pooled connections. Called when an application is torn down in tests."""
    engine.dispose()
