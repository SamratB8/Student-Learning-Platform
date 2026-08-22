"""Persistence mapping for audit events.

The table is append-oriented: there is no update path and no ``updated_at`` column,
because an audit record that can be edited is not evidence. Restricting DELETE and
UPDATE at the database-role level is a deployment concern and is listed as
outstanding work in docs/DEVELOPMENT.md.

Columns are deliberately institution-neutral. Scope is stored as text such as
``BRANCH:<id>`` rather than as a database enum, so adding a scope type or a branch is
configuration rather than a migration.
"""

from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Index, String, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from learning_platform.infrastructure.database.base import Base

__all__ = ["AuditEventRecord"]


class AuditEventRecord(Base):
    """One stored security or administrative event."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(PgUUID(as_uuid=True), primary_key=True)

    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    """When the action happened, as asserted by the caller's clock. Distinct from
    ``recorded_at`` so a delayed background handler does not misreport the time."""

    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=text("now()")
    )
    """When the row was written, set by the database rather than the application."""

    action: Mapped[str] = mapped_column(String(128), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False)

    actor_kind: Mapped[str] = mapped_column(String(16), nullable=False)
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    """No foreign key to a users table. An audit record must survive the deletion or
    archival of the account it refers to."""

    target_type: Mapped[str | None] = mapped_column(String(64), nullable=True)
    target_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    scope: Mapped[str | None] = mapped_column(String(128), nullable=True)
    reason_code: Mapped[str | None] = mapped_column(String(64), nullable=True)
    correlation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    context: Mapped[dict[str, Any]] = mapped_column(
        JSONB, nullable=False, server_default=text("'{}'::jsonb")
    )
    """Small scalar values that explain the decision. The domain rejects sensitive
    field names before a record reaches this table."""

    __table_args__ = (
        # Supports the common queries: an administrator reviewing recent activity,
        # investigating one actor, and reconstructing a single request.
        Index("ix_audit_events_occurred_at", occurred_at.desc()),
        Index("ix_audit_events_actor_user_id_occurred_at", actor_user_id, occurred_at.desc()),
        Index("ix_audit_events_action_occurred_at", action, occurred_at.desc()),
        Index("ix_audit_events_correlation_id", correlation_id),
    )
