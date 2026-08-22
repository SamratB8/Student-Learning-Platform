"""Alembic environment.

The connection URL comes from the application's validated settings rather than from
``alembic.ini``, so there is exactly one source of truth for which database is being
targeted, and no credential is ever written into a committed file.

Every mapped class must be imported here. Alembic compares ``Base.metadata`` against
the live database, and a model that is never imported is simply invisible, which
silently produces a migration that drops nothing and creates nothing.
"""

from __future__ import annotations

from alembic import context
from sqlalchemy import engine_from_config, pool

# Imported for the side effect of registering tables on Base.metadata.
from learning_platform.infrastructure.audit import models as audit_models  # noqa: F401
from learning_platform.infrastructure.config.settings import load_settings
from learning_platform.infrastructure.database.base import Base
from learning_platform.infrastructure.tasks import models as task_models  # noqa: F401

config = context.config

target_metadata = Base.metadata

settings = load_settings()
if not settings.database_configured:
    raise SystemExit(
        "DATABASE_URL is not configured. Set it in .env or the environment before running Alembic."
    )

# set_main_option escapes the value, so a password containing '%' survives intact.
config.set_main_option(
    "sqlalchemy.url", settings.database_url.get_secret_value().replace("%", "%%")
)


def run_migrations_offline() -> None:
    """Emit SQL to stdout instead of executing it.

    Used to review a migration before it touches a deployed database.
    """
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations against a live connection."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        # No pooling: a migration run is a single short-lived connection.
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            # Detect column type and server-default drift, which Alembic ignores by
            # default and which is a common source of an environment diverging.
            compare_type=True,
            compare_server_default=True,
            # Each migration runs in its own transaction, so a failure cannot leave
            # a partially applied revision behind.
            transaction_per_migration=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
