"""Persistence mapping for dispatched background work.

One table, ``task_dispatch``, which is both the outbox and the queue of record under
ADR 0004. Business writes and the tasks they owe are inserted in the same
transaction, so the two can never disagree: there is no window in which a course was
marked synced but the follow-up indexing request was lost to a failed network call,
and none in which work was queued for a change that was rolled back.

The row is not a message. It is the platform's own record of work it owes itself, and
it outlives whatever delivery mechanism is carrying it at the time.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any, Final

from sqlalchemy import CheckConstraint, DateTime, Index, Integer, SmallInteger, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.domain.tasks import TaskState
from learning_platform.infrastructure.database.base import Base

__all__ = ["TASK_DISPATCH_STATES", "TaskDispatchRecord"]

TASK_DISPATCH_STATES: Final[tuple[str, ...]] = tuple(state.value for state in TaskState)


class TaskDispatchRecord(Base):
    """One durable request for background work."""

    __tablename__ = "task_dispatch"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    task_type: Mapped[str] = mapped_column(String(128), nullable=False)
    """A registered task type such as ``classroom.sync_course``.

    Stored as text, not a database enum. Adding a task type is then a code change and
    a registry entry rather than a migration, and an enum could not be shortened
    later anyway. What stops this column selecting arbitrary code is the registry,
    not the column type.
    """

    payload_version: Mapped[int] = mapped_column(SmallInteger, nullable=False, server_default="1")
    """Which schema ``payload`` follows.

    Present from the first migration because rows outlive deployments. A task
    dispatched by the running version may still be pending when the next version
    starts draining, and that version needs to know what shape it is looking at
    rather than inferring it from the keys present.
    """

    payload: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    """Internal identifiers and scalars. The domain rejects sensitive field names and
    non-scalar values before a payload can reach this column."""

    state: Mapped[str] = mapped_column(String(16), nullable=False)

    available_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """The earliest time this task may run. Carries both a requested delay and, after
    a retryable failure, the backoff."""

    claimed_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When the current claim expires.

    A deadline rather than a token, because the runtime is serverless and an
    invocation can be killed without ever running cleanup. A row whose lease has
    passed is simply due again, which makes recovery a property of the ordinary claim
    query instead of a separate reaper that could itself fail.
    """

    attempt_count: Mapped[int] = mapped_column(Integer, nullable=False, server_default="0")
    max_attempts: Mapped[int] = mapped_column(Integer, nullable=False, server_default="5")

    last_error_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    """A short slug such as ``provider_timeout``.

    Never an exception message and never a traceback. Both routinely quote the values
    that caused them, and this row holds a payload in the next column along. Full
    diagnostics belong in the operational log, which is redacted.
    """

    idempotency_key: Mapped[str | None] = mapped_column(String(200), nullable=True, unique=True)
    """Deduplicates a dispatch derived from the same business fact.

    Nullable, and NULLs do not collide in PostgreSQL, so work that has no natural key
    is simply never deduplicated rather than being forced to invent one.
    """

    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    """When the task reached a terminal state. Also the basis for pruning succeeded
    rows later, which is why it is set for every terminal state and not just success."""

    __table_args__ = (
        CheckConstraint(
            "state IN ('" + "', '".join(TASK_DISPATCH_STATES) + "')",
            name="state_is_known",
        ),
        CheckConstraint("attempt_count >= 0", name="attempt_count_is_not_negative"),
        CheckConstraint("max_attempts >= 1", name="max_attempts_permits_one_try"),
        CheckConstraint("payload_version >= 1", name="payload_version_starts_at_one"),
        # The claim query's two branches: work that is due, and work whose lease
        # expired. Both are (state, timestamp) range scans, and both stay selective
        # because terminal rows accumulate but never match either predicate.
        Index("ix_task_dispatch_state_available_at", state, available_at),
        Index("ix_task_dispatch_state_claimed_until", state, claimed_until),
        # Answers "what did this request set in motion", which is the question asked
        # while investigating one user's report.
        Index("ix_task_dispatch_correlation_id", correlation_id),
    )
