"""PostgreSQL-backed tests.

ADR 0001 requires integration tests to run against real PostgreSQL. These are skipped
when ``DATABASE_URL`` is unset rather than falling back to SQLite, because a SQLite
substitute would silently stop exercising JSONB, UUID, timezone-aware timestamps, and
transaction behaviour, which is exactly what these tests exist to check.

Each test runs inside a transaction that is rolled back, so the development database
is left unchanged and tests do not depend on each other's order.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from learning_platform.domain.audit import (
    AuditActor,
    AuditActorKind,
    AuditOutcome,
    AuditTarget,
    record_audit_event,
)
from learning_platform.domain.identifiers import new_internal_id
from learning_platform.infrastructure.audit.models import AuditEventRecord
from learning_platform.infrastructure.audit.sink import SqlAlchemyAuditSink
from learning_platform.infrastructure.config.settings import AppEnvironment, Settings
from learning_platform.infrastructure.database.engine import build_engine, check_connection
from learning_platform.infrastructure.database.unit_of_work import UnitOfWorkFactory

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def engine(database_url: str) -> Iterator[Engine]:
    settings = Settings(
        app_env=AppEnvironment.TEST,
        deployment_key="test",
        database_url=SecretStr(database_url),
    )
    created = build_engine(settings)
    if not check_connection(created):
        created.dispose()
        pytest.skip("DATABASE_URL is set but PostgreSQL is not reachable")
    yield created
    created.dispose()


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is always rolled back.

    ``join_transaction_mode="create_savepoint"`` means the session works inside a
    savepoint of the outer transaction. Without it, a test that provokes an
    IntegrityError would leave the outer transaction deassociated and break teardown.
    """
    connection = engine.connect()
    transaction = connection.begin()
    open_session = Session(
        bind=connection,
        expire_on_commit=False,
        join_transaction_mode="create_savepoint",
    )
    yield open_session
    open_session.close()
    transaction.rollback()
    connection.close()


class TestConnectivity:
    def test_the_database_answers(self, engine: Engine) -> None:
        assert check_connection(engine) is True

    def test_the_target_is_postgresql(self, engine: Engine) -> None:
        """Guards against an integration run that silently used another database."""
        assert engine.dialect.name == "postgresql"

    def test_timestamps_come_back_timezone_aware(self, session: Session) -> None:
        value = session.execute(text("SELECT now()")).scalar_one()
        assert value.tzinfo is not None


class TestMigrationsApplied:
    def test_the_audit_table_exists(self, engine: Engine) -> None:
        """Fails with a clear message when migrations have not been run."""
        assert "audit_events" in inspect(engine).get_table_names(), (
            "run 'uv run alembic upgrade head' before the integration tests"
        )

    def test_the_alembic_version_table_exists(self, engine: Engine) -> None:
        assert "alembic_version" in inspect(engine).get_table_names()

    def test_the_model_matches_the_migrated_table(self, engine: Engine) -> None:
        """Catches a model changed without a matching migration."""
        actual = {column["name"] for column in inspect(engine).get_columns("audit_events")}
        expected = {column.name for column in AuditEventRecord.__table__.columns}
        assert expected == actual

    def test_the_expected_indexes_exist(self, engine: Engine) -> None:
        indexes = {index["name"] for index in inspect(engine).get_indexes("audit_events")}
        assert "ix_audit_events_occurred_at" in indexes
        assert "ix_audit_events_correlation_id" in indexes


class TestAuditPersistence:
    def _sink(self, session: Session) -> SqlAlchemyAuditSink:
        return SqlAlchemyAuditSink(session)

    def test_an_event_round_trips(self, session: Session) -> None:
        user_id = new_internal_id()
        target_id = new_internal_id()
        event = record_audit_event(
            action="users.approve",
            outcome=AuditOutcome.ALLOWED,
            actor=AuditActor(kind=AuditActorKind.USER, user_id=user_id),
            occurred_at=datetime.now(UTC),
            target=AuditTarget(target_type="application", target_id=target_id),
            scope="BRANCH:0b1d",
            reason_code="identity_verified",
            correlation_id="correlation-abc",
            context={"queue_length": 4},
        )

        self._sink(session).record(event)
        session.flush()

        stored = session.get(AuditEventRecord, event.event_id)
        assert stored is not None
        assert stored.action == "users.approve"
        assert stored.outcome == "allowed"
        assert stored.actor_user_id == user_id
        assert stored.target_id == target_id
        assert stored.scope == "BRANCH:0b1d"
        assert stored.correlation_id == "correlation-abc"
        # JSONB round trip, which a SQLite substitute would not exercise.
        assert stored.context == {"queue_length": 4}

    def test_occurred_at_is_stored_timezone_aware(self, session: Session) -> None:
        event = record_audit_event(
            action="users.approve",
            outcome=AuditOutcome.ALLOWED,
            actor=AuditActor(kind=AuditActorKind.SYSTEM),
            occurred_at=datetime.now(UTC),
        )
        self._sink(session).record(event)
        session.flush()

        stored = session.get(AuditEventRecord, event.event_id)
        assert stored is not None
        assert stored.occurred_at.tzinfo is not None

    def test_recorded_at_is_set_by_the_database(self, session: Session) -> None:
        """The application does not get to decide when the row was written."""
        event = record_audit_event(
            action="users.approve",
            outcome=AuditOutcome.ALLOWED,
            actor=AuditActor(kind=AuditActorKind.SYSTEM),
            occurred_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
        self._sink(session).record(event)
        session.flush()
        session.expire_all()

        stored = session.get(AuditEventRecord, event.event_id)
        assert stored is not None
        assert stored.recorded_at.year >= 2026

    def test_a_denied_outcome_is_stored(self, session: Session) -> None:
        event = record_audit_event(
            action="resources.download",
            outcome=AuditOutcome.DENIED,
            actor=AuditActor(kind=AuditActorKind.ANONYMOUS),
            occurred_at=datetime.now(UTC),
            reason_code="not_a_member",
        )
        self._sink(session).record(event)
        session.flush()

        stored = session.get(AuditEventRecord, event.event_id)
        assert stored is not None
        assert stored.outcome == "denied"
        assert stored.actor_user_id is None

    def test_the_action_column_is_not_nullable(self, session: Session) -> None:
        session.add(
            AuditEventRecord(
                id=new_internal_id(),
                occurred_at=datetime.now(UTC),
                action=None,
                outcome="allowed",
                actor_kind="system",
            )
        )
        with pytest.raises(IntegrityError):
            session.flush()
        # A failed flush leaves the session needing a rollback before it can be used
        # or closed again.
        session.rollback()


class TestUnitOfWork:
    def test_a_clean_exit_commits(self, engine: Engine) -> None:
        factory = UnitOfWorkFactory(engine)
        event = record_audit_event(
            action="users.approve",
            outcome=AuditOutcome.ALLOWED,
            actor=AuditActor(kind=AuditActorKind.SYSTEM),
            occurred_at=datetime.now(UTC),
        )

        with factory() as unit_of_work:
            unit_of_work.audit.record(event)

        with factory() as verifying:
            assert verifying.session.get(AuditEventRecord, event.event_id) is not None

        # Clean up, since this test deliberately commits outside the rollback fixture.
        with factory() as cleanup:
            stored = cleanup.session.get(AuditEventRecord, event.event_id)
            if stored is not None:
                cleanup.session.delete(stored)

    def test_an_exception_rolls_everything_back(self, engine: Engine) -> None:
        factory = UnitOfWorkFactory(engine)
        event = record_audit_event(
            action="users.approve",
            outcome=AuditOutcome.ALLOWED,
            actor=AuditActor(kind=AuditActorKind.SYSTEM),
            occurred_at=datetime.now(UTC),
        )

        with pytest.raises(RuntimeError, match="use case failed"), factory() as unit_of_work:
            unit_of_work.audit.record(event)
            raise RuntimeError("use case failed")

        with factory() as verifying:
            assert verifying.session.get(AuditEventRecord, event.event_id) is None

    def test_the_original_exception_is_not_swallowed(self, engine: Engine) -> None:
        """A unit of work must never hide the failure that caused its own rollback."""
        with pytest.raises(ValueError, match="original cause"), UnitOfWorkFactory(engine)():
            raise ValueError("original cause")

    def test_the_session_is_unavailable_outside_the_context_manager(self, engine: Engine) -> None:
        """Otherwise work could happen with no transaction boundary."""
        unit_of_work = UnitOfWorkFactory(engine)()
        with pytest.raises(RuntimeError, match="not active"):
            _ = unit_of_work.session
