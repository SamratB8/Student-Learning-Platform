"""Draining due work, with no database, no HTTP, and no queue.

The runner is the piece ADR 0004 makes replaceable runtimes plug into, so it is
tested entirely against fakes. If these tests ever need a real dependency to pass,
the layering has slipped.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Self

import pytest

from learning_platform.application.ports.task_store import ClaimedTask
from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.application.tasks.runner import TaskRunner
from learning_platform.domain.clock import FixedClock
from learning_platform.domain.identifiers import InternalId, new_internal_id
from learning_platform.domain.tasks import (
    RetryPolicy,
    TaskFailed,
    TaskFailureKind,
    TaskState,
    TaskType,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)
DEMO = TaskType("demo.run")


@dataclass
class RecordedOutcome:
    task_id: InternalId
    state: TaskState
    error_code: str | None
    available_at: datetime | None


class FakeStore:
    """A dispatch store that hands out a prepared batch and remembers outcomes."""

    def __init__(self, queued: Sequence[ClaimedTask] = ()) -> None:
        self.queued = list(queued)
        self.outcomes: list[RecordedOutcome] = []
        self.claims: list[tuple[int, int]] = []

    def claim_due(self, *, now: datetime, limit: int, lease_seconds: int) -> Sequence[ClaimedTask]:
        self.claims.append((limit, lease_seconds))
        batch = self.queued[:limit]
        del self.queued[:limit]
        return batch

    def record_outcome(
        self,
        *,
        task_id: InternalId,
        state: TaskState,
        now: datetime,
        error_code: str | None = None,
        available_at: datetime | None = None,
    ) -> None:
        self.outcomes.append(
            RecordedOutcome(
                task_id=task_id,
                state=state,
                error_code=error_code,
                available_at=available_at,
            )
        )

    def enqueue(self, **_kwargs: object) -> tuple[InternalId, bool]:  # pragma: no cover
        raise NotImplementedError


class FakeUnitOfWork:
    """Records how transactions were opened and closed."""

    def __init__(self, store: FakeStore, journal: list[str]) -> None:
        self._store = store
        self._journal = journal

    @property
    def task_store(self) -> FakeStore:
        return self._store

    def __enter__(self) -> Self:
        self._journal.append("begin")
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self._journal.append("commit" if exc_type is None else "rollback")

    def commit(self) -> None:  # pragma: no cover - unused by the runner
        self._journal.append("commit")

    def rollback(self) -> None:  # pragma: no cover - unused by the runner
        self._journal.append("rollback")


class ObservedEvent:
    def __init__(self, name: str, state: TaskState | None, error_code: str | None) -> None:
        self.name = name
        self.state = state
        self.error_code = error_code


class RecordingObserver:
    def __init__(self) -> None:
        self.events: list[ObservedEvent] = []

    def started(self, task: ClaimedTask) -> None:
        self.events.append(ObservedEvent("started", None, None))

    def finished(
        self,
        task: ClaimedTask,
        *,
        state: TaskState,
        duration_ms: float,
        error_code: str | None = None,
    ) -> None:
        self.events.append(ObservedEvent("finished", state, error_code))


def _task(
    *,
    attempt: int = 1,
    max_attempts: int = 5,
    task_type: TaskType = DEMO,
    payload_version: int = 1,
) -> ClaimedTask:
    return ClaimedTask(
        task_id=new_internal_id(),
        task_type=task_type,
        payload_version=payload_version,
        payload={"course_id": "0198f0"},
        attempt=attempt,
        max_attempts=max_attempts,
        correlation_id="correlation-abc",
    )


def _runner(
    store: FakeStore,
    registry: TaskRegistry,
    *,
    journal: list[str] | None = None,
    retry_policy: RetryPolicy | None = None,
    batch_limit: int = 10,
    observer: RecordingObserver | None = None,
) -> TaskRunner:
    entries = journal if journal is not None else []
    return TaskRunner(
        unit_of_work=lambda: FakeUnitOfWork(store, entries),
        registry=registry,
        clock=FixedClock(NOW),
        retry_policy=retry_policy,
        batch_limit=batch_limit,
        observer=observer,
    )


def _registry_running(handler: object) -> TaskRegistry:
    registry = TaskRegistry()
    registry.register(DEMO, handler)  # type: ignore[arg-type]
    return registry


def _build_runner(*, lease_seconds: int = 300, batch_limit: int = 10) -> TaskRunner:
    """Construct a runner, for tests that care about rejected configuration."""
    return TaskRunner(
        unit_of_work=lambda: FakeUnitOfWork(FakeStore(), []),
        registry=TaskRegistry(),
        clock=FixedClock(NOW),
        lease_seconds=lease_seconds,
        batch_limit=batch_limit,
    )


class TestNothingDue:
    def test_an_empty_queue_reports_nothing(self) -> None:
        store = FakeStore()
        report = _runner(store, TaskRegistry()).drain()

        assert report.claimed == 0
        assert report.is_empty is True
        assert store.outcomes == []


class TestSuccess:
    def test_a_handler_runs_with_its_payload(self) -> None:
        seen: list[TaskContext] = []
        task = _task()
        store = FakeStore([task])

        _runner(store, _registry_running(seen.append)).drain()

        assert len(seen) == 1
        assert seen[0].task_id == task.task_id
        assert seen[0].payload == {"course_id": "0198f0"}
        assert seen[0].attempt == 1
        assert seen[0].correlation_id == "correlation-abc"

    def test_success_is_recorded(self) -> None:
        task = _task()
        store = FakeStore([task])

        report = _runner(store, _registry_running(lambda _c: None)).drain()

        assert report.succeeded == 1
        assert [outcome.state for outcome in store.outcomes] == [TaskState.SUCCEEDED]
        assert store.outcomes[0].error_code is None

    def test_several_tasks_all_run(self) -> None:
        store = FakeStore([_task(), _task(), _task()])
        report = _runner(store, _registry_running(lambda _c: None)).drain()

        assert report.claimed == 3
        assert report.succeeded == 3


class TestRetryableFailure:
    def test_it_returns_to_pending_with_backoff(self) -> None:
        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.PROVIDER, "provider_timeout")

        store = FakeStore([_task(attempt=1)])
        report = _runner(
            store,
            _registry_running(fail),
            retry_policy=RetryPolicy(max_attempts=5, base_delay_seconds=30),
        ).drain()

        assert report.retried == 1
        outcome = store.outcomes[0]
        assert outcome.state is TaskState.PENDING
        assert outcome.error_code == "provider_timeout"
        assert outcome.available_at == NOW + timedelta(seconds=30)

    def test_backoff_widens_with_the_attempt(self) -> None:
        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.INFRASTRUCTURE, "connection_lost")

        store = FakeStore([_task(attempt=3)])
        _runner(
            store,
            _registry_running(fail),
            retry_policy=RetryPolicy(max_attempts=5, base_delay_seconds=30),
        ).drain()

        assert store.outcomes[0].available_at == NOW + timedelta(seconds=120)

    def test_an_unclassified_exception_is_treated_as_retryable(self) -> None:
        """Giving up on anything an author forgot to classify would discard work."""

        def explode(_context: TaskContext) -> None:
            raise RuntimeError("connection to db.internal:5432 failed for user admin")

        store = FakeStore([_task(attempt=1)])
        report = _runner(store, _registry_running(explode)).drain()

        assert report.retried == 1
        assert store.outcomes[0].state is TaskState.PENDING
        assert store.outcomes[0].error_code == "unhandled_exception"


class TestExhaustion:
    def test_the_last_attempt_exhausts_rather_than_retrying(self) -> None:
        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.PROVIDER, "provider_timeout")

        store = FakeStore([_task(attempt=3, max_attempts=3)])
        report = _runner(
            store, _registry_running(fail), retry_policy=RetryPolicy(max_attempts=3)
        ).drain()

        assert report.exhausted == 1
        assert store.outcomes[0].state is TaskState.EXHAUSTED
        assert store.outcomes[0].available_at is None

    def test_the_task_budget_wins_over_the_policy_default(self) -> None:
        """A dispatch that asked for one attempt gets one, whatever the default is."""

        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.PROVIDER, "provider_timeout")

        store = FakeStore([_task(attempt=1, max_attempts=1)])
        report = _runner(
            store, _registry_running(fail), retry_policy=RetryPolicy(max_attempts=10)
        ).drain()

        assert report.exhausted == 1

    def test_retrying_cannot_continue_for_ever(self) -> None:
        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.INFRASTRUCTURE, "connection_lost")

        policy = RetryPolicy(max_attempts=4)
        registry = _registry_running(fail)
        states: list[TaskState] = []

        for attempt in range(1, 6):
            store = FakeStore([_task(attempt=attempt, max_attempts=4)])
            _runner(store, registry, retry_policy=policy).drain()
            states.append(store.outcomes[0].state)

        assert states == [
            TaskState.PENDING,
            TaskState.PENDING,
            TaskState.PENDING,
            TaskState.EXHAUSTED,
            TaskState.EXHAUSTED,
        ]


class TestTerminalFailure:
    def test_a_non_retryable_failure_does_not_retry(self) -> None:
        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.INVALID_PAYLOAD, "missing_course_id")

        store = FakeStore([_task(attempt=1, max_attempts=5)])
        report = _runner(store, _registry_running(fail)).drain()

        assert report.failed == 1
        assert store.outcomes[0].state is TaskState.FAILED
        assert store.outcomes[0].available_at is None

    def test_a_revoked_permission_fails_terminally(self) -> None:
        """Authorization is revalidated at execution, and losing it is not transient."""

        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.AUTHORIZATION_INVALIDATED, "grant_revoked")

        store = FakeStore([_task()])
        report = _runner(store, _registry_running(fail)).drain()

        assert report.failed == 1
        assert store.outcomes[0].error_code == "grant_revoked"

    def test_an_unregistered_task_type_fails_without_running_anything(self) -> None:
        store = FakeStore([_task(task_type=TaskType("never.registered"))])
        report = _runner(store, TaskRegistry()).drain()

        assert report.failed == 1
        assert store.outcomes[0].state is TaskState.FAILED
        assert store.outcomes[0].error_code == "unknown_task_type"

    def test_an_unsupported_payload_version_fails_without_running_anything(self) -> None:
        ran: list[TaskContext] = []
        registry = TaskRegistry()
        registry.register(DEMO, ran.append, payload_versions=(1,))
        store = FakeStore([_task(payload_version=9)])

        report = _runner(store, registry).drain()

        assert report.failed == 1
        assert store.outcomes[0].error_code == "unsupported_payload_version"
        assert ran == []


class TestIsolationBetweenTasks:
    def test_one_failing_task_does_not_stop_the_others(self) -> None:
        """A poisoned task must not halt every other piece of work in the system."""
        good_one, bad, good_two = _task(), _task(), _task()

        def handler(context: TaskContext) -> None:
            if context.task_id == bad.task_id:
                raise TaskFailed(TaskFailureKind.PROVIDER, "provider_timeout")

        store = FakeStore([good_one, bad, good_two])
        report = _runner(store, _registry_running(handler)).drain()

        assert report.claimed == 3
        assert report.succeeded == 2
        assert report.retried == 1

    def test_drain_does_not_raise_when_a_handler_does(self) -> None:
        """The caller is a scheduler with nowhere useful to put an exception."""

        def explode(_context: TaskContext) -> None:
            raise RuntimeError("boom")

        store = FakeStore([_task()])
        _runner(store, _registry_running(explode)).drain()


class TestTransactionBoundaries:
    def test_the_claim_commits_before_any_handler_runs(self) -> None:
        """A lease only visible inside an open transaction protects nothing."""
        journal: list[str] = []
        order: list[str] = []

        def handler(_context: TaskContext) -> None:
            order.append(f"handler-after-{len(journal)}-journal-entries")

        store = FakeStore([_task()])
        _runner(store, _registry_running(handler), journal=journal).drain()

        # begin, commit for the claim; then the handler; then begin, commit for the
        # outcome.
        assert journal[:2] == ["begin", "commit"]
        assert order == ["handler-after-2-journal-entries"]

    def test_the_outcome_is_recorded_in_its_own_transaction(self) -> None:
        """A failing handler must not be able to roll back the record of its failure,
        or the attempt counter would never advance."""
        journal: list[str] = []

        def fail(_context: TaskContext) -> None:
            raise TaskFailed(TaskFailureKind.PROVIDER, "provider_timeout")

        store = FakeStore([_task()])
        _runner(store, _registry_running(fail), journal=journal).drain()

        assert journal == ["begin", "commit", "begin", "commit"]
        assert store.outcomes[0].state is TaskState.PENDING


class TestBatching:
    def test_a_drain_claims_no_more_than_its_batch_limit(self) -> None:
        store = FakeStore([_task() for _ in range(20)])
        report = _runner(store, _registry_running(lambda _c: None), batch_limit=5).drain()

        assert report.claimed == 5
        assert store.claims == [(5, 300)]

    def test_a_caller_may_ask_for_less_but_never_more(self) -> None:
        """Bounded so a drain finishes inside an invocation budget."""
        store = FakeStore([_task() for _ in range(20)])
        _runner(store, _registry_running(lambda _c: None), batch_limit=5).drain(limit=50)

        assert store.claims == [(5, 300)]

    def test_a_lease_of_no_time_is_refused(self) -> None:
        with pytest.raises(ValueError, match="lease"):
            _build_runner(lease_seconds=0)

    def test_a_batch_of_no_tasks_is_refused(self) -> None:
        with pytest.raises(ValueError, match="at least one task"):
            _build_runner(batch_limit=0)


class TestObservation:
    def test_start_and_finish_are_reported(self) -> None:
        observer = RecordingObserver()
        store = FakeStore([_task()])
        _runner(store, _registry_running(lambda _c: None), observer=observer).drain()

        assert [event.name for event in observer.events] == ["started", "finished"]
        assert observer.events[1].state is TaskState.SUCCEEDED

    def test_a_failure_is_still_reported_as_finished(self) -> None:
        """Otherwise a correlation binding made at start would never be released."""
        observer = RecordingObserver()

        def explode(_context: TaskContext) -> None:
            raise RuntimeError("boom")

        store = FakeStore([_task()])
        _runner(store, _registry_running(explode), observer=observer).drain()

        assert [event.name for event in observer.events] == ["started", "finished"]
        assert observer.events[1].error_code == "unhandled_exception"

    def test_an_unknown_task_type_is_still_reported(self) -> None:
        observer = RecordingObserver()
        store = FakeStore([_task(task_type=TaskType("never.registered"))])
        _runner(store, TaskRegistry(), observer=observer).drain()

        assert [event.name for event in observer.events] == ["started", "finished"]
        assert observer.events[1].state is TaskState.FAILED
