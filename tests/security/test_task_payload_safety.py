"""What must never end up in a dispatch row or a log line.

A task record is durable, is read by operators, and sits next to its own payload. The
two failure modes worth guarding are a secret reaching the payload column, and an
exception message reaching the error column: the second is subtle, because the
obvious implementation of "record why this failed" is to store ``str(exc)``, and
exception text routinely quotes the value that caused it.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest

from learning_platform.application.ports.task_store import ClaimedTask
from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.application.tasks.runner import TaskRunner
from learning_platform.domain.clock import FixedClock
from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.identifiers import InternalId, new_internal_id
from learning_platform.domain.tasks import TaskState, TaskType, validate_task_payload

CANARY = "hunter2-pw0canary"
DEMO = TaskType("demo.run")
NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class CapturingStore:
    """Remembers exactly what the runner asked to be written."""

    def __init__(self, task: ClaimedTask) -> None:
        self._queued = [task]
        self.recorded: list[dict[str, object]] = []

    def claim_due(self, *, now: datetime, limit: int, lease_seconds: int) -> list[ClaimedTask]:
        batch = self._queued[:limit]
        del self._queued[:limit]
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
        self.recorded.append({"state": state, "error_code": error_code})

    def enqueue(self, **_kwargs: object) -> tuple[InternalId, bool]:  # pragma: no cover
        raise NotImplementedError


class FakeUnitOfWork:
    def __init__(self, store: CapturingStore) -> None:
        self._store = store

    @property
    def task_store(self) -> CapturingStore:
        return self._store

    def __enter__(self) -> FakeUnitOfWork:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        return None

    def commit(self) -> None:  # pragma: no cover
        return None

    def rollback(self) -> None:  # pragma: no cover
        return None


class TestSecretsCannotReachAPayload:
    @pytest.mark.parametrize(
        "key",
        [
            "access_token",
            "refresh_token",
            "oauth_token",
            "password",
            "client_secret",
            "private_key",
            "signing_key",
            "session_key",
            "recovery_key",
            "cookie",
            "authorization",
            "signed_url",
            "plaintext",
            "ciphertext",
        ],
    )
    def test_the_forbidden_field_names_are_refused(self, key: str) -> None:
        """SECURITY_MODEL.md lists these as excluded from durable records."""
        with pytest.raises(InvariantViolation, match="sensitive"):
            validate_task_payload({key: CANARY})

    def test_a_matrix_key_cannot_be_dispatched(self) -> None:
        with pytest.raises(InvariantViolation):
            validate_task_payload({"device_private_key": CANARY})

    def test_the_guard_is_a_guard_and_not_a_boundary(self) -> None:
        """A secret under an innocuous name still passes, and this documents that.

        What keeps secrets out is the rule that payloads carry internal identifiers
        only. This check makes breaking that rule noisy in the common cases; it
        cannot make it impossible, and pretending otherwise would be worse than
        saying so.
        """
        validate_task_payload({"note": CANARY})


class TestFailuresArePersistedWithoutDetail:
    def _drain_with(self, handler: object) -> CapturingStore:
        task = ClaimedTask(
            task_id=new_internal_id(),
            task_type=DEMO,
            payload_version=1,
            payload={"course_id": "0198f0"},
            attempt=1,
            max_attempts=3,
        )
        store = CapturingStore(task)
        registry = TaskRegistry()
        registry.register(DEMO, handler)  # type: ignore[arg-type]

        TaskRunner(
            unit_of_work=lambda: FakeUnitOfWork(store),
            registry=registry,
            clock=FixedClock(NOW),
        ).drain()
        return store

    def test_an_exception_message_is_not_persisted(self) -> None:
        def explode(_context: TaskContext) -> None:
            raise RuntimeError(f"could not connect as admin with password {CANARY}")

        store = self._drain_with(explode)

        assert store.recorded == [{"state": TaskState.PENDING, "error_code": "unhandled_exception"}]
        assert CANARY not in repr(store.recorded)

    def test_a_database_error_quoting_a_row_is_not_persisted(self) -> None:
        """The realistic case: driver errors echo the statement and its parameters."""

        def explode(_context: TaskContext) -> None:
            raise ValueError(
                f"duplicate key value violates constraint: Key (email)=({CANARY}) exists"
            )

        store = self._drain_with(explode)
        assert CANARY not in repr(store.recorded)

    def test_only_a_slug_is_ever_recorded(self) -> None:
        def explode(_context: TaskContext) -> None:
            raise RuntimeError("anything at all")

        store = self._drain_with(explode)
        recorded_code = store.recorded[0]["error_code"]
        assert isinstance(recorded_code, str)
        assert recorded_code.replace("_", "").isalnum()
        assert len(recorded_code) <= 63


class TestLoggingDoesNotEchoPayloads:
    def test_the_observer_logs_no_payload(self) -> None:
        """Identity, type, state, attempt, timing. Never the payload itself."""
        from pathlib import Path

        source = (
            Path(__file__).resolve().parents[2]
            / "src"
            / "learning_platform"
            / "infrastructure"
            / "tasks"
            / "observer.py"
        ).read_text(encoding="utf-8-sig")

        assert "task.payload" not in source
        assert "payload=" not in source

    def test_the_error_column_is_bounded_in_the_schema(self) -> None:
        """A short column is the backstop if a future change tries to store prose."""
        from sqlalchemy import String

        from learning_platform.infrastructure.tasks.models import TaskDispatchRecord

        column = TaskDispatchRecord.__table__.columns["last_error_code"]
        assert isinstance(column.type, String)
        assert column.type.length == 64
