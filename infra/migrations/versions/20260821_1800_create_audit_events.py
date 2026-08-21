"""Create the audit_events table.

The first migration. Deliberately limited to the audit trail: it is needed by every
later phase, it is institution-neutral, and it introduces no CTS-specific enum or
table. The rest of the schema in docs/DATA_MODEL.md arrives with the features that
require it.

Revision ID: 0001_audit_events
Revises:
Create Date: 2026-08-21 18:00:00+00:00

"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_audit_events"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        # Application-generated UUIDv7. No server default, so the identifier exists
        # before the row does and does not depend on a database extension.
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        # When the action happened, per the caller's clock.
        sa.Column("occurred_at", sa.DateTime(timezone=True), nullable=False),
        # When the row was written, per the database. Kept separate so a delayed
        # background handler cannot misreport when something actually happened.
        sa.Column(
            "recorded_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("action", sa.String(length=128), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("actor_kind", sa.String(length=16), nullable=False),
        # No foreign key by design: an audit record must outlive the account it
        # refers to, including after archival or erasure.
        sa.Column("actor_user_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("target_type", sa.String(length=64), nullable=True),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=True),
        # Text such as 'BRANCH:<id>', not a database enum, so adding a scope type or
        # a branch stays configuration rather than a migration.
        sa.Column("scope", sa.String(length=128), nullable=True),
        sa.Column("reason_code", sa.String(length=64), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column(
            "context",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_audit_events")),
    )

    # Descending on time: every read of this table is "most recent first".
    op.create_index(
        "ix_audit_events_occurred_at",
        "audit_events",
        [sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_actor_user_id_occurred_at",
        "audit_events",
        ["actor_user_id", sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_action_occurred_at",
        "audit_events",
        ["action", sa.text("occurred_at DESC")],
        unique=False,
    )
    op.create_index(
        "ix_audit_events_correlation_id",
        "audit_events",
        ["correlation_id"],
        unique=False,
    )


def downgrade() -> None:
    # Reversible only because the table is new and empty in any environment where a
    # downgrade is legitimate. Once this table holds real records, dropping it
    # destroys the audit trail, which is why restricting DELETE at the database-role
    # level is listed as outstanding deployment work in docs/DEVELOPMENT.md.
    op.drop_index("ix_audit_events_correlation_id", table_name="audit_events")
    op.drop_index("ix_audit_events_action_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_actor_user_id_occurred_at", table_name="audit_events")
    op.drop_index("ix_audit_events_occurred_at", table_name="audit_events")
    op.drop_table("audit_events")
