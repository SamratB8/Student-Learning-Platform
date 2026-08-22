"""Create the task_dispatch table.

The durable record of background work (ADR 0004). It is both the outbox and the queue
of record: a task is inserted in the same transaction as the business change that
owes it, and a scheduled drain claims and runs it later.

Institution-neutral, like every table here. Task types are text validated by an
application-side registry rather than a database enum, so adding one is a code change
rather than a migration, and no deployment-specific name appears in the schema.

Revision ID: 0002_task_dispatch
Revises: 0001_audit_events
Create Date: 2026-08-23 10:00:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0002_task_dispatch"
down_revision: str | None = "0001_audit_events"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Kept as a literal rather than imported from the model. A migration records what the
# schema was at this revision; importing the current enum would let a later code
# change silently rewrite the history of what this migration did.
_STATES = ("pending", "claimed", "succeeded", "failed", "exhausted", "cancelled")


def upgrade() -> None:
    op.create_table(
        "task_dispatch",
        # Application-generated UUIDv7, as elsewhere: identity exists before the row.
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("task_type", sa.String(length=128), nullable=False),
        # Present from the first revision because rows outlive deployments: work
        # dispatched by one version may still be pending when the next drains it.
        sa.Column("payload_version", sa.SmallInteger(), server_default="1", nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("state", sa.String(length=16), nullable=False),
        sa.Column("available_at", sa.DateTime(timezone=True), nullable=False),
        # A lease deadline, not a lock. A row whose claim has expired is simply due
        # again, so an invocation killed mid-handler needs no cleanup to have run.
        sa.Column("claimed_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("max_attempts", sa.Integer(), server_default="5", nullable=False),
        # A short slug such as 'provider_timeout'. Never a message or a traceback:
        # both quote the values that caused them, and the payload is one column away.
        sa.Column("last_error_code", sa.String(length=64), nullable=True),
        sa.Column("idempotency_key", sa.String(length=200), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_task_dispatch")),
        # Enforced in the database as well as the domain. The application is the only
        # writer today, but a stray state written by a migration or a manual fix
        # would otherwise be invisible until a drain tried to transition from it.
        sa.CheckConstraint(
            "state IN ('" + "', '".join(_STATES) + "')",
            name=op.f("ck_task_dispatch_state_is_known"),
        ),
        sa.CheckConstraint(
            "attempt_count >= 0", name=op.f("ck_task_dispatch_attempt_count_is_not_negative")
        ),
        sa.CheckConstraint(
            "max_attempts >= 1", name=op.f("ck_task_dispatch_max_attempts_permits_one_try")
        ),
        sa.CheckConstraint(
            "payload_version >= 1", name=op.f("ck_task_dispatch_payload_version_starts_at_one")
        ),
        # Deduplication is a database guarantee, not an application check. Two
        # concurrent requests deriving the same key must produce one task even when
        # neither can see the other's uncommitted insert.
        sa.UniqueConstraint("idempotency_key", name=op.f("uq_task_dispatch_idempotency_key")),
    )

    # The claim query has two branches, and each gets an index. Both stay selective
    # as the table grows because terminal rows accumulate but match neither
    # predicate: 'pending' rows that are due, and 'claimed' rows whose lease expired.
    op.create_index(
        "ix_task_dispatch_state_available_at",
        "task_dispatch",
        ["state", "available_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_dispatch_state_claimed_until",
        "task_dispatch",
        ["state", "claimed_until"],
        unique=False,
    )
    # Answers "what did this request set in motion", which is the question actually
    # asked when investigating one user's report.
    op.create_index(
        "ix_task_dispatch_correlation_id",
        "task_dispatch",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    # Safe to reverse only while this table holds no work that matters. Dropping it
    # discards every pending and failed task, which is data loss rather than a schema
    # change, so a downgrade in an environment with real traffic must be preceded by
    # draining the table.
    op.drop_index("ix_task_dispatch_correlation_id", table_name="task_dispatch")
    op.drop_index("ix_task_dispatch_state_claimed_until", table_name="task_dispatch")
    op.drop_index("ix_task_dispatch_state_available_at", table_name="task_dispatch")
    op.drop_table("task_dispatch")
