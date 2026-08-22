"""Audit sink backed by the caller's SQLAlchemy session."""

from __future__ import annotations

from sqlalchemy.orm import Session

from learning_platform.domain.audit import AuditEvent
from learning_platform.infrastructure.audit.models import AuditEventRecord

__all__ = ["SqlAlchemyAuditSink"]


class SqlAlchemyAuditSink:
    """Writes audit events into the caller's transaction.

    Implements ``application.ports.audit_sink.AuditSink``. It does not commit: the
    unit of work does, so a rolled-back action leaves no record of having happened,
    and a committed one always carries its evidence.
    """

    def __init__(self, session: Session) -> None:
        self._session = session

    def record(self, event: AuditEvent) -> None:
        """Stage one audit event for writing."""
        self._session.add(
            AuditEventRecord(
                id=event.event_id,
                occurred_at=event.occurred_at,
                action=event.action,
                outcome=event.outcome.value,
                actor_kind=event.actor.kind.value,
                actor_user_id=event.actor.user_id,
                target_type=event.target.target_type if event.target else None,
                target_id=event.target.target_id if event.target else None,
                scope=event.scope,
                reason_code=event.reason_code,
                correlation_id=event.correlation_id,
                context=dict(event.context),
            )
        )
