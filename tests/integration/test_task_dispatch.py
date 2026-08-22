"""Durable dispatch against real PostgreSQL.

Everything here depends on behaviour SQLite does not have and a fake would have to
imitate: ``ON CONFLICT DO NOTHING``, ``FOR UPDATE SKIP LOCKED``, JSONB round trips,
timezone-aware timestamps, and genuine transaction isolation between two connections.
Those are precisely the properties ADR 0004 relies on, so they are tested against the
real thing or not at all.

Tests that commit clean up after themselves through the ``clean_dispatch`` fixture.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr
from sqlalchemy import Engine, inspect, text
from sqlalchemy.exc import DBAPIError, IntegrityError
from sqlalchemy.orm import Session

from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.application.tasks.runner import TaskRunner
from learning_platform.domain.clock import FixedClock, SystemClock
from learning_platform.domain.errors import InvariantViolation, NotFound
from learning_platform.domain.identifiers import InternalId, new_internal_id
from learning_platform.domain.tasks import RetryPolicy, TaskState, TaskType
from learning_platform.infrastructure.config.settings import AppEnvironment, Settings
from learning_platform.infrastructure.database.engine import build_engine, check_connection
from learning_platform.infrastructure.database.unit_of_work import UnitOfWorkFactory
from learning_platform.infrastructure.tasks.models import TaskDispatchRecord
from learning_platform.infrastructure.tasks.repository import SqlAlchemyTaskDispatchStore

pytestmark = pytest.mark.integration

DEMO = TaskType("demo.run")
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


def _registry(handler: object = None) -> TaskRegistry:
    registry = TaskRegistry()
    registry.register(DEMO, handler or (lambda _context: None))  # type: ignore[arg-type]
    return registry


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
def clean_dispatch(engine: Engine) -> Iterator[None]:
    """Empty the dispatch table around a test that commits."""
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE task_dispatch"))
    yield
    with engine.begin() as connection:
        connection.execute(text("TRUNCATE TABLE task_dispatch"))


@pytest.fixture
def session(engine: Engine) -> Iterator[Session]:
    """A session whose work is always rolled back."""
    connection = engine.connect()
    transaction = connection.begin()
    open_session = Session(
        bind=connection, expire_on_commit=False, join_transaction_mode="create_savepoint"
    )
    yield open_session
    open_session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def store(session: Session) -> SqlAlchemyTaskDispatchStore:
    return SqlAlchemyTaskDispatchStore(session)


def _enqueue(
    store: SqlAlchemyTaskDispatchStore,
    *,
    available_at: datetime | None = None,
    idempotency_key: str | None = None,
    payload: dict[str, object] | None = None,
    payload_version: int = 1,
    max_attempts: int = 5,
    correlation_id: str | None = None,
) -> tuple[InternalId, bool]:
    return store.enqueue(
        task_type=DEMO,
        payload=payload or {"course_id": "0198f0"},  # type: ignore[arg-type]
        payload_version=payload_version,
        available_at=available_at or NOW,
        max_attempts=max_attempts,
        idempotency_key=idempotency_key,
        correlation_id=correlation_id,
    )


class TestMigrationApplied:
    def test_the_table_exists(self, engine: Engine) -> None:
        assert "task_dispatch" in inspect(engine).get_table_names(), (
            "run 'uv run alembic upgrade head' before the integration tests"
        )

    def test_the_model_matches_the_migrated_table(self, engine: Engine) -> None:
        """Catches a model changed without a matching migration."""
        actual = {column["name"] for column in inspect(engine).get_columns("task_dispatch")}
        expected = {column.name for column in TaskDispatchRecord.__table__.columns}
        assert expected == actual

    def test_the_claim_indexes_exist(self, engine: Engine) -> None:
        """Without these the claim query degrades to a scan as terminal rows pile up."""
        indexes = {index["name"] for index in inspect(engine).get_indexes("task_dispatch")}
        assert "ix_task_dispatch_state_available_at" in indexes
        assert "ix_task_dispatch_state_claimed_until" in indexes
        assert "ix_task_dispatch_correlation_id" in indexes

    def test_the_idempotency_key_is_unique_in_the_database(self, engine: Engine) -> None:
        constraints = inspect(engine).get_unique_constraints("task_dispatch")
        assert any(constraint["column_names"] == ["idempotency_key"] for constraint in constraints)

    def test_both_tables_are_present_after_migration(self, engine: Engine) -> None:
        tables = set(inspect(engine).get_table_names())
        assert {"audit_events", "task_dispatch", "alembic_version"} <= tables


class TestDatabaseConstraints:
    def test_an_unknown_state_is_refused(self, session: Session) -> None:
        """The domain is the first line, the check constraint is the backstop."""
        session.add(
            TaskDispatchRecord(
                id=new_internal_id(),
                task_type="demo.run",
                state="in_flight_ish",
                available_at=NOW,
                max_attempts=5,
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)):
            session.flush()
        session.rollback()

    def test_a_zero_attempt_budget_is_refused(self, session: Session) -> None:
        session.add(
            TaskDispatchRecord(
                id=new_internal_id(),
                task_type="demo.run",
                state="pending",
                available_at=NOW,
                max_attempts=0,
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)):
            session.flush()
        session.rollback()

    def test_payload_version_zero_is_refused(self, session: Session) -> None:
        session.add(
            TaskDispatchRecord(
                id=new_internal_id(),
                task_type="demo.run",
                state="pending",
                available_at=NOW,
                max_attempts=5,
                payload_version=0,
            )
        )
        with pytest.raises((IntegrityError, DBAPIError)):
            session.flush()
        session.rollback()


class TestEnqueue:
    def test_a_task_round_trips(self, store: SqlAlchemyTaskDispatchStore, session: Session) -> None:
        task_id, duplicate = _enqueue(
            store, payload={"course_id": "0198f0", "revision": 4, "force": True}
        )

        assert duplicate is False
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.task_type == "demo.run"
        assert stored.state == "pending"
        assert stored.attempt_count == 0
        # JSONB round trip, including a boolean and an integer.
        assert stored.payload == {"course_id": "0198f0", "revision": 4, "force": True}

    def test_timestamps_come_back_timezone_aware(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        task_id, _ = _enqueue(store)
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.available_at.tzinfo is not None
        assert stored.created_at.tzinfo is not None

    def test_the_payload_version_is_stored(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        """A later deployment must be able to tell what shape an old row is."""
        task_id, _ = _enqueue(store, payload_version=3)
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.payload_version == 3

    def test_a_correlation_id_is_stored(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        task_id, _ = _enqueue(store, correlation_id="correlation-abc")
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.correlation_id == "correlation-abc"


class TestIdempotency:
    def test_a_repeated_key_records_one_task(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        first, first_duplicate = _enqueue(store, idempotency_key="course-1-rev-2")
        second, second_duplicate = _enqueue(store, idempotency_key="course-1-rev-2")

        assert first_duplicate is False
        assert second_duplicate is True
        assert second == first

        total = session.execute(
            text("SELECT count(*) FROM task_dispatch WHERE idempotency_key = 'course-1-rev-2'")
        ).scalar_one()
        assert total == 1

    def test_a_duplicate_does_not_poison_the_transaction(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        """The caller is usually a retried request that has no idea it is the second.

        A raised IntegrityError here would abort the whole business transaction over
        something that is not an error at all.
        """
        _enqueue(store, idempotency_key="course-1-rev-2")
        _enqueue(store, idempotency_key="course-1-rev-2")

        # The transaction is still usable, which it would not be after a constraint
        # violation had been allowed to surface.
        later, _ = _enqueue(store, idempotency_key="course-1-rev-3")
        assert session.get(TaskDispatchRecord, later) is not None

    def test_unkeyed_tasks_never_collide(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        """NULLs do not conflict in PostgreSQL, so work with no natural key is never
        forced to invent one."""
        first, _ = _enqueue(store, idempotency_key=None)
        second, _ = _enqueue(store, idempotency_key=None)

        assert first != second
        # Counted by identifier rather than as a table total, so the assertion means
        # "these two both exist" and not "nothing else has ever been written here".
        assert session.get(TaskDispatchRecord, first) is not None
        assert session.get(TaskDispatchRecord, second) is not None

    def test_different_keys_are_separate_tasks(self, store: SqlAlchemyTaskDispatchStore) -> None:
        first, _ = _enqueue(store, idempotency_key="course-1-rev-2")
        second, duplicate = _enqueue(store, idempotency_key="course-1-rev-3")
        assert first != second
        assert duplicate is False


class TestTransactionSemantics:
    """The outbox property: work is owed if and only if the change that owes it landed."""

    def test_a_committed_use_case_leaves_its_task(
        self, engine: Engine, clean_dispatch: None
    ) -> None:
        factory = UnitOfWorkFactory(engine, task_registry=_registry(), clock=SystemClock())

        with factory() as unit_of_work:
            receipt = unit_of_work.tasks.dispatch(DEMO, {"course_id": "0198f0"})

        with factory() as verifying:
            assert verifying.session.get(TaskDispatchRecord, receipt.task_id) is not None

    def test_a_rolled_back_use_case_leaves_no_task(
        self, engine: Engine, clean_dispatch: None
    ) -> None:
        """Queued work for a change that never happened is the failure the outbox exists
        to prevent."""
        factory = UnitOfWorkFactory(engine, task_registry=_registry(), clock=SystemClock())
        captured: list[object] = []

        with pytest.raises(RuntimeError, match="use case failed"), factory() as unit_of_work:
            receipt = unit_of_work.tasks.dispatch(DEMO, {"course_id": "0198f0"})
            captured.append(receipt.task_id)
            raise RuntimeError("use case failed")

        with factory() as verifying:
            assert verifying.session.get(TaskDispatchRecord, captured[0]) is None

    def test_business_writes_and_dispatch_commit_together(
        self, engine: Engine, clean_dispatch: None
    ) -> None:
        """Both land, or neither does. Proven with the audit table as the business write."""
        from learning_platform.domain.audit import (
            AuditActor,
            AuditActorKind,
            AuditOutcome,
            record_audit_event,
        )
        from learning_platform.infrastructure.audit.models import AuditEventRecord

        factory = UnitOfWorkFactory(engine, task_registry=_registry(), clock=SystemClock())
        event = record_audit_event(
            action="resources.publish",
            outcome=AuditOutcome.ALLOWED,
            actor=AuditActor(kind=AuditActorKind.SYSTEM),
            occurred_at=datetime.now(UTC),
        )
        captured: list[object] = []

        with pytest.raises(RuntimeError), factory() as unit_of_work:
            unit_of_work.audit.record(event)
            captured.append(unit_of_work.tasks.dispatch(DEMO, {}).task_id)
            raise RuntimeError("failed after both writes")

        with factory() as verifying:
            assert verifying.session.get(AuditEventRecord, event.event_id) is None
            assert verifying.session.get(TaskDispatchRecord, captured[0]) is None

    def test_dispatching_an_unregistered_type_is_refused(self, engine: Engine) -> None:
        factory = UnitOfWorkFactory(engine, task_registry=TaskRegistry(), clock=SystemClock())
        with pytest.raises(InvariantViolation, match="no registered handler"), factory() as uow:
            uow.tasks.dispatch(DEMO, {})

    def test_a_unit_of_work_without_a_registry_refuses_to_dispatch(self, engine: Engine) -> None:
        with (
            pytest.raises(RuntimeError, match="no task registry"),
            UnitOfWorkFactory(engine)() as uow,
        ):
            _ = uow.tasks


class TestClaiming:
    def test_a_due_task_is_claimed(self, store: SqlAlchemyTaskDispatchStore) -> None:
        task_id, _ = _enqueue(store, available_at=NOW)
        claimed = store.claim_due(now=NOW, limit=10, lease_seconds=300)

        assert [task.task_id for task in claimed] == [task_id]
        assert claimed[0].task_type == DEMO
        assert claimed[0].payload == {"course_id": "0198f0"}

    def test_claiming_increments_the_attempt(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        task_id, _ = _enqueue(store)
        claimed = store.claim_due(now=NOW, limit=10, lease_seconds=300)

        assert claimed[0].attempt == 1
        session.expire_all()
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.attempt_count == 1
        assert stored.state == "claimed"
        assert stored.claimed_until == NOW + timedelta(seconds=300)

    def test_a_future_task_is_not_claimed(self, store: SqlAlchemyTaskDispatchStore) -> None:
        """Delayed dispatch, and retry backoff, both rely on this."""
        _enqueue(store, available_at=NOW + timedelta(minutes=5))
        assert store.claim_due(now=NOW, limit=10, lease_seconds=300) == []

    def test_a_task_becomes_claimable_once_its_time_arrives(
        self, store: SqlAlchemyTaskDispatchStore
    ) -> None:
        _enqueue(store, available_at=NOW + timedelta(minutes=5))
        claimed = store.claim_due(now=NOW + timedelta(minutes=6), limit=10, lease_seconds=300)
        assert len(claimed) == 1

    def test_a_claimed_task_is_not_handed_out_again(
        self, store: SqlAlchemyTaskDispatchStore
    ) -> None:
        _enqueue(store)
        assert len(store.claim_due(now=NOW, limit=10, lease_seconds=300)) == 1
        assert store.claim_due(now=NOW, limit=10, lease_seconds=300) == []

    def test_an_expired_lease_is_reclaimed(self, store: SqlAlchemyTaskDispatchStore) -> None:
        """The recovery path: an invocation killed mid-handler leaves this behind, and
        nothing else exists to notice."""
        _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)

        reclaimed = store.claim_due(now=NOW + timedelta(seconds=301), limit=10, lease_seconds=300)
        assert len(reclaimed) == 1
        assert reclaimed[0].attempt == 2

    def test_a_live_lease_is_respected(self, store: SqlAlchemyTaskDispatchStore) -> None:
        _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        assert store.claim_due(now=NOW + timedelta(seconds=299), limit=10, lease_seconds=300) == []

    def test_the_limit_is_respected(self, store: SqlAlchemyTaskDispatchStore) -> None:
        for index in range(5):
            _enqueue(store, idempotency_key=f"key-{index}")
        assert len(store.claim_due(now=NOW, limit=2, lease_seconds=300)) == 2

    def test_the_oldest_work_is_claimed_first(self, store: SqlAlchemyTaskDispatchStore) -> None:
        """Otherwise a steady arrival of new work starves whatever has been waiting."""
        oldest, _ = _enqueue(store, available_at=NOW - timedelta(hours=2), idempotency_key="a")
        _enqueue(store, available_at=NOW - timedelta(hours=1), idempotency_key="b")
        _enqueue(store, available_at=NOW, idempotency_key="c")

        claimed = store.claim_due(now=NOW, limit=1, lease_seconds=300)
        assert claimed[0].task_id == oldest

    def test_a_claim_of_nothing_is_refused(self, store: SqlAlchemyTaskDispatchStore) -> None:
        with pytest.raises(InvariantViolation):
            store.claim_due(now=NOW, limit=0, lease_seconds=300)

    def test_terminal_tasks_are_never_claimed(self, store: SqlAlchemyTaskDispatchStore) -> None:
        task_id, _ = _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        store.record_outcome(task_id=task_id, state=TaskState.SUCCEEDED, now=NOW)

        assert store.claim_due(now=NOW + timedelta(days=1), limit=10, lease_seconds=300) == []


class TestConcurrentClaiming:
    def test_two_runners_never_receive_the_same_task(
        self, engine: Engine, clean_dispatch: None
    ) -> None:
        """The property the whole design rests on, tested across two real connections.

        The first connection claims inside an open transaction. The second must not
        block behind it and must not receive the same row: ``FOR UPDATE SKIP LOCKED``
        makes it step over the locked row rather than wait.
        """
        factory = UnitOfWorkFactory(engine, task_registry=_registry(), clock=SystemClock())
        with factory() as seeding:
            for index in range(4):
                seeding.tasks.dispatch(DEMO, {}, idempotency_key=f"concurrent-{index}")

        now = datetime.now(UTC)
        first_connection = engine.connect()
        first_transaction = first_connection.begin()
        first_session = Session(bind=first_connection, join_transaction_mode="create_savepoint")

        try:
            first_batch = SqlAlchemyTaskDispatchStore(first_session).claim_due(
                now=now, limit=2, lease_seconds=300
            )
            # Deliberately not committed: the rows are locked by an in-flight
            # transaction, which is exactly the racing runner scenario.
            with factory() as second:
                second_batch = second.task_store.claim_due(now=now, limit=4, lease_seconds=300)

            first_ids = {task.task_id for task in first_batch}
            second_ids = {task.task_id for task in second_batch}

            assert len(first_batch) == 2
            assert first_ids.isdisjoint(second_ids), "a task was claimed by two runners"
        finally:
            first_transaction.rollback()
            first_connection.close()


class TestRecordingOutcomes:
    def test_success_is_terminal_and_timestamped(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        task_id, _ = _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        store.record_outcome(task_id=task_id, state=TaskState.SUCCEEDED, now=NOW)

        session.expire_all()
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.state == "succeeded"
        assert stored.completed_at is not None
        assert stored.claimed_until is None

    def test_a_retry_returns_to_pending_with_a_new_time(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        task_id, _ = _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        retry_at = NOW + timedelta(seconds=30)
        store.record_outcome(
            task_id=task_id,
            state=TaskState.PENDING,
            now=NOW,
            error_code="provider_timeout",
            available_at=retry_at,
        )

        session.expire_all()
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.state == "pending"
        assert stored.available_at == retry_at
        assert stored.last_error_code == "provider_timeout"
        assert stored.completed_at is None
        assert stored.claimed_until is None

    def test_a_retried_task_is_claimed_again_once_due(
        self, store: SqlAlchemyTaskDispatchStore
    ) -> None:
        task_id, _ = _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        store.record_outcome(
            task_id=task_id,
            state=TaskState.PENDING,
            now=NOW,
            error_code="provider_timeout",
            available_at=NOW + timedelta(seconds=30),
        )

        assert store.claim_due(now=NOW + timedelta(seconds=10), limit=10, lease_seconds=300) == []
        again = store.claim_due(now=NOW + timedelta(seconds=31), limit=10, lease_seconds=300)
        assert len(again) == 1
        assert again[0].attempt == 2

    def test_returning_to_pending_without_a_time_is_refused(
        self, store: SqlAlchemyTaskDispatchStore
    ) -> None:
        task_id, _ = _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        with pytest.raises(InvariantViolation, match="time to run again"):
            store.record_outcome(task_id=task_id, state=TaskState.PENDING, now=NOW)

    def test_an_illegal_transition_is_refused(self, store: SqlAlchemyTaskDispatchStore) -> None:
        """Succeeding without ever being claimed would mean work ran without a lease."""
        task_id, _ = _enqueue(store)
        with pytest.raises(InvariantViolation):
            store.record_outcome(task_id=task_id, state=TaskState.SUCCEEDED, now=NOW)

    def test_completing_twice_is_refused(self, store: SqlAlchemyTaskDispatchStore) -> None:
        task_id, _ = _enqueue(store)
        store.claim_due(now=NOW, limit=10, lease_seconds=300)
        store.record_outcome(task_id=task_id, state=TaskState.SUCCEEDED, now=NOW)

        with pytest.raises(InvariantViolation):
            store.record_outcome(task_id=task_id, state=TaskState.SUCCEEDED, now=NOW)

    def test_an_unknown_task_is_not_found(self, store: SqlAlchemyTaskDispatchStore) -> None:
        with pytest.raises(NotFound):
            store.record_outcome(task_id=new_internal_id(), state=TaskState.SUCCEEDED, now=NOW)

    def test_a_pending_task_may_be_cancelled(
        self, store: SqlAlchemyTaskDispatchStore, session: Session
    ) -> None:
        task_id, _ = _enqueue(store)
        store.record_outcome(task_id=task_id, state=TaskState.CANCELLED, now=NOW)

        session.expire_all()
        stored = session.get(TaskDispatchRecord, task_id)
        assert stored is not None
        assert stored.state == "cancelled"


class TestEndToEnd:
    """Dispatch inside a transaction, then drain it, exactly as a deployment would."""

    def test_a_dispatched_task_is_executed_by_a_drain(
        self, engine: Engine, clean_dispatch: None
    ) -> None:
        seen: list[TaskContext] = []
        registry = _registry(seen.append)
        factory = UnitOfWorkFactory(engine, task_registry=registry, clock=SystemClock())

        with factory() as unit_of_work:
            receipt = unit_of_work.tasks.dispatch(
                DEMO, {"course_id": "0198f0"}, correlation_id="correlation-abc"
            )

        report = TaskRunner(unit_of_work=factory, registry=registry, clock=SystemClock()).drain()

        assert report.claimed == 1
        assert report.succeeded == 1
        assert len(seen) == 1
        assert seen[0].task_id == receipt.task_id
        assert seen[0].correlation_id == "correlation-abc"

        with factory() as verifying:
            stored = verifying.session.get(TaskDispatchRecord, receipt.task_id)
            assert stored is not None
            assert stored.state == "succeeded"

    def test_a_failing_task_is_retried_then_exhausted(
        self, engine: Engine, clean_dispatch: None
    ) -> None:
        """The full retry lifecycle against the real table."""
        attempts: list[int] = []

        def always_fails(context: TaskContext) -> None:
            attempts.append(context.attempt)
            raise RuntimeError("provider is down")

        registry = _registry(always_fails)
        factory = UnitOfWorkFactory(engine, task_registry=registry, clock=SystemClock())

        with factory() as unit_of_work:
            receipt = unit_of_work.tasks.dispatch(DEMO, {}, max_attempts=3)

        policy = RetryPolicy(max_attempts=3, base_delay_seconds=1)
        moment = datetime.now(UTC)
        for _ in range(3):
            TaskRunner(
                unit_of_work=factory,
                registry=registry,
                clock=FixedClock(moment),
                retry_policy=policy,
            ).drain()
            # Jump past the backoff rather than sleeping through it.
            moment = moment + timedelta(hours=1)

        assert attempts == [1, 2, 3]
        with factory() as verifying:
            stored = verifying.session.get(TaskDispatchRecord, receipt.task_id)
            assert stored is not None
            assert stored.state == "exhausted"
            assert stored.attempt_count == 3
            assert stored.last_error_code == "unhandled_exception"

    def test_a_deduplicated_dispatch_runs_once(self, engine: Engine, clean_dispatch: None) -> None:
        """Two identical requests, one piece of work. The Classroom-sync invariant."""
        seen: list[TaskContext] = []
        registry = _registry(seen.append)
        factory = UnitOfWorkFactory(engine, task_registry=registry, clock=SystemClock())

        for _ in range(3):
            with factory() as unit_of_work:
                unit_of_work.tasks.dispatch(DEMO, {}, idempotency_key="course-1-rev-2")

        report = TaskRunner(unit_of_work=factory, registry=registry, clock=SystemClock()).drain()

        assert report.claimed == 1
        assert len(seen) == 1

    def test_the_shipped_verification_task_runs(self, engine: Engine, clean_dispatch: None) -> None:
        """The one task type Phase 1B ships, end to end."""
        from learning_platform.worker import build_task_registry
        from learning_platform.worker.maintenance import VERIFY_DISPATCH

        registry = build_task_registry()
        factory = UnitOfWorkFactory(engine, task_registry=registry, clock=SystemClock())

        with factory() as unit_of_work:
            receipt = unit_of_work.tasks.dispatch(VERIFY_DISPATCH, {"note": "phase-1b"})

        report = TaskRunner(unit_of_work=factory, registry=registry, clock=SystemClock()).drain()

        assert report.succeeded == 1
        with factory() as verifying:
            stored = verifying.session.get(TaskDispatchRecord, receipt.task_id)
            assert stored is not None
            assert stored.state == "succeeded"


class TestDrainEndpointWithADatabase:
    """The happy path of the invocation endpoint, which needs real storage."""

    def test_an_authenticated_drain_runs_due_work(
        self, database_url: str, clean_dispatch: None
    ) -> None:
        from learning_platform.web import create_app
        from learning_platform.web.extensions import get_extensions
        from learning_platform.worker.maintenance import VERIFY_DISPATCH

        secret = "a-drain-secret-of-sufficient-length"
        application = create_app(
            Settings(
                app_env=AppEnvironment.TEST,
                deployment_key="test",
                database_url=SecretStr(database_url),
                task_runner_secret=SecretStr(secret),
            )
        )
        try:
            extensions = get_extensions(application)
            with extensions.unit_of_work() as unit_of_work:
                unit_of_work.tasks.dispatch(VERIFY_DISPATCH, {})

            client = application.test_client()

            assert client.post("/internal/tasks/drain").status_code == 401

            response = client.post(
                "/internal/tasks/drain", headers={"Authorization": f"Bearer {secret}"}
            )
            assert response.status_code == 200
            assert response.get_json() == {
                "status": "ok",
                "claimed": 1,
                "succeeded": 1,
                "retried": 0,
                "exhausted": 0,
                "failed": 0,
            }

            # Nothing left to do, and the second drain says so rather than repeating.
            again = client.post(
                "/internal/tasks/drain", headers={"Authorization": f"Bearer {secret}"}
            )
            assert again.get_json()["claimed"] == 0
        finally:
            get_extensions(application).shutdown()
