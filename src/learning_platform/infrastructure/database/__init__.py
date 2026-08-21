"""PostgreSQL persistence: engine, declarative base, and the unit of work."""

from learning_platform.infrastructure.database.base import Base, metadata
from learning_platform.infrastructure.database.engine import (
    build_engine,
    check_connection,
    dispose_engine,
)
from learning_platform.infrastructure.database.unit_of_work import (
    SqlAlchemyUnitOfWork,
    UnitOfWorkFactory,
)

__all__ = [
    "Base",
    "SqlAlchemyUnitOfWork",
    "UnitOfWorkFactory",
    "build_engine",
    "check_connection",
    "dispose_engine",
    "metadata",
]
