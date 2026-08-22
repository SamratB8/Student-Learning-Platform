"""PostgreSQL implementation of the dispatch store.

Two pieces of SQL carry the design, and both are here rather than spread across the
application layer because both depend on PostgreSQL semantics that a portable query
could not express.

``claim_due`` is a single statement. Selecting rows and then updating them would let
two runners select the same row before either wrote anything back; ``FOR UPDATE SKIP
LOCKED`` inside the update makes claiming atomic, and lets a second runner work on
different rows instead of blocking behind the first.

``enqueue`` uses ``ON CONFLICT DO NOTHING``. Checking for an existing key first and
inserting if absent is the same race one level up, and losing it would abort the
caller's whole transaction over a duplicate that was expected.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import Select, select, text, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.orm import Session

from learning_platform.application.ports.task_store import ClaimedTask
from learning_platform.domain.errors import InvariantViolation, NotFound
from learning_platform.domain.identifiers import InternalId, new_internal_id
from learning_platform.domain.tasks import (
    TaskPayload,
    TaskState,
    TaskType,
    ensure_transition,
)
from learning_platform.infrastructure.tasks.models import TaskDispatchRecord

__all__ = ["SqlAlchemyTaskDispatchStore"]


class SqlAlchemyTaskDispatchStore:
    """Dispatch storage bound to one transaction.

    Implements ``application.ports.task_store.TaskDispatchStore``. It never commits:
    the unit of work does, which is what makes a dispatch atomic with the business
    change that asked for it.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def enqueue(
        self,
        *,
        task_type: TaskType,
        payload: TaskPayload,
        payload_version: int,
        available_at: datetime,
        max_attempts: int,
        idempotency_key: str | None,
        correlation_id: str | None,
    ) -> tuple[InternalId, bool]:
        """Insert a pending task, or adopt the existing one with the same key."""
        task_id = new_internal_id()
        values: dict[str, Any] = {
            "id": task_id,
            "task_type": str(task_type),
            "payload": dict(payload),
            "payload_version": payload_version,
            "state": TaskState.PENDING.value,
            "available_at": available_at,
            "attempt_count": 0,
            "max_attempts": max_attempts,
            "idempotency_key": idempotency_key,
            "correlation_id": correlation_id,
            "updated_at": available_at,
        }

        if idempotency_key is None:
            # No key means no deduplication is possible or wanted. NULLs never
            # collide in PostgreSQL, so an ON CONFLICT clause here would be
            # decoration rather than behaviour.
            self._session.execute(postgresql_insert(TaskDispatchRecord).values(**values))
            return task_id, False

        statement = (
            postgresql_insert(TaskDispatchRecord)
            .values(**values)
            .on_conflict_do_nothing(index_elements=["idempotency_key"])
            .returning(TaskDispatchRecord.id)
        )
        inserted = self._session.execute(statement).scalar_one_or_none()
        if inserted is not None:
            return InternalId(inserted), False

        existing = self._session.execute(
            select(TaskDispatchRecord.id).where(
                TaskDispatchRecord.idempotency_key == idempotency_key
            )
        ).scalar_one()
        return InternalId(existing), True

    def claim_due(self, *, now: datetime, limit: int, lease_seconds: int) -> Sequence[ClaimedTask]:
        """Lease due work atomically, returning what was claimed."""
        if limit < 1:
            raise InvariantViolation("a claim must ask for at least one task")

        due = self._due_selection(now=now, limit=limit)
        claimed = (
            update(TaskDispatchRecord)
            .where(TaskDispatchRecord.id.in_(due.scalar_subquery()))
            .values(
                state=TaskState.CLAIMED.value,
                attempt_count=TaskDispatchRecord.attempt_count + 1,
                claimed_until=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
            .returning(
                TaskDispatchRecord.id,
                TaskDispatchRecord.task_type,
                TaskDispatchRecord.payload_version,
                TaskDispatchRecord.payload,
                TaskDispatchRecord.attempt_count,
                TaskDispatchRecord.max_attempts,
                TaskDispatchRecord.correlation_id,
            )
            # The UPDATE writes rows the session may already hold. Without this the
            # session's copies would be stale for the rest of the transaction.
            .execution_options(synchronize_session=False)
        )

        return [
            ClaimedTask(
                task_id=InternalId(row.id),
                task_type=TaskType(row.task_type),
                payload_version=row.payload_version,
                payload=dict(row.payload),
                attempt=row.attempt_count,
                max_attempts=row.max_attempts,
                correlation_id=row.correlation_id,
            )
            for row in self._session.execute(claimed)
        ]

    def _due_selection(self, *, now: datetime, limit: int) -> Select[tuple[Any]]:
        """Rows eligible to run, locked so a concurrent runner skips them.

        Two branches. The first is ordinary due work. The second reclaims a task
        whose lease expired, which is how an invocation killed mid-handler releases
        its work without any cleanup having run.

        Ordered oldest-first so a task that has been waiting does not starve behind a
        steady arrival of newer work.
        """
        pending = (TaskDispatchRecord.state == TaskState.PENDING.value) & (
            TaskDispatchRecord.available_at <= now
        )
        lease_expired = (TaskDispatchRecord.state == TaskState.CLAIMED.value) & (
            TaskDispatchRecord.claimed_until <= now
        )
        return (
            select(TaskDispatchRecord.id)
            .where(pending | lease_expired)
            .order_by(TaskDispatchRecord.available_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )

    def record_outcome(
        self,
        *,
        task_id: InternalId,
        state: TaskState,
        now: datetime,
        error_code: str | None = None,
        available_at: datetime | None = None,
    ) -> None:
        """Move a task to ``state``, refusing an illegal transition."""
        if state is TaskState.PENDING and available_at is None:
            raise InvariantViolation("a task returned to pending needs a time to run again")

        current = self._session.execute(
            select(TaskDispatchRecord.state)
            .where(TaskDispatchRecord.id == task_id)
            .with_for_update()
        ).scalar_one_or_none()
        if current is None:
            raise NotFound("no such dispatched task")

        # Raises if, for example, two runners both believed they owned this row: the
        # second finds a terminal state and is refused rather than overwriting the
        # first outcome.
        ensure_transition(TaskState(current), state)

        values: dict[str, Any] = {
            "state": state.value,
            "updated_at": now,
            "claimed_until": None,
            "completed_at": now if state.is_terminal else None,
        }
        if error_code is not None:
            values["last_error_code"] = error_code
        if available_at is not None:
            values["available_at"] = available_at

        self._session.execute(
            update(TaskDispatchRecord)
            .where(TaskDispatchRecord.id == task_id)
            .values(**values)
            .execution_options(synchronize_session=False)
        )

    def count_by_state(self) -> dict[str, int]:
        """How many tasks are in each state.

        Not part of the port. Used by tests and by operational inspection, and kept
        here rather than exposed through the application layer because nothing in a
        use case should be branching on queue depth.
        """
        rows = self._session.execute(
            text("SELECT state, count(*) AS total FROM task_dispatch GROUP BY state")
        )
        return {row.state: row.total for row in rows}
