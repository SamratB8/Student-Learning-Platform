"""Security and administrative audit records.

An ``AuditEvent`` is a domain record, not a log line. The distinction matters:

* Operational logs describe how the software behaved. They are for the maintainer,
  are allowed to be noisy, and may be sampled, rotated, or dropped.
* Audit events describe what a principal did to what, and whether it was permitted.
  They are append-oriented, retained deliberately, and readable only with the
  ``audit.read`` capability.

Writing a log line is never a substitute for writing an audit event, and neither is
the reverse.

This module defines the record and its invariants. Persistence lives in
infrastructure behind the :class:`AuditSink` port.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Final

from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.identifiers import InternalId, new_internal_id
from learning_platform.domain.sensitive import is_sensitive_key

__all__ = [
    "AuditActor",
    "AuditActorKind",
    "AuditEvent",
    "AuditOutcome",
    "AuditTarget",
    "record_audit_event",
]

# Dotted lowercase action names, matching the capability catalogue in PERMISSIONS.md
# (for example ``users.approve``). Constraining the shape keeps the audit trail
# queryable instead of becoming free-form prose.
_ACTION_PATTERN: Final = re.compile(r"^[a-z][a-z0-9_]*(?:\.[a-z][a-z0-9_]*)+$")

_MAX_CONTEXT_ENTRIES: Final = 24
_MAX_CONTEXT_VALUE_LENGTH: Final = 256

type AuditContextValue = str | int | bool | None


class AuditActorKind(StrEnum):
    """What kind of principal acted."""

    USER = "user"
    """An authenticated platform user."""

    ANONYMOUS = "anonymous"
    """An unauthenticated request. Recorded because failed attempts matter."""

    SERVICE = "service"
    """A machine identity, such as the restricted draft publisher."""

    SYSTEM = "system"
    """The platform acting on its own behalf, such as a scheduled reconciliation."""


class AuditOutcome(StrEnum):
    """Whether the attempted action succeeded, was refused, or broke."""

    ALLOWED = "allowed"
    DENIED = "denied"
    FAILED = "failed"
    """The action was permitted but could not be completed. Distinct from DENIED so
    an integration outage is never mistaken for an authorization decision."""


@dataclass(frozen=True, slots=True)
class AuditActor:
    """The principal responsible for an audited action."""

    kind: AuditActorKind
    user_id: InternalId | None = None

    def __post_init__(self) -> None:
        if self.kind is AuditActorKind.USER and self.user_id is None:
            raise InvariantViolation("a user actor requires a user identifier")
        if self.kind is not AuditActorKind.USER and self.user_id is not None:
            raise InvariantViolation("only a user actor may carry a user identifier")


@dataclass(frozen=True, slots=True)
class AuditTarget:
    """What the action was performed on.

    ``target_type`` is a stable domain name such as ``resource`` or ``application``.
    ``target_id`` is an internal identifier; provider identifiers are not used here
    because they are not primary business keys.
    """

    target_type: str
    target_id: InternalId | None = None

    def __post_init__(self) -> None:
        if not self.target_type:
            raise InvariantViolation("an audit target requires a type")


@dataclass(frozen=True, slots=True)
class AuditEvent:
    """One append-oriented security or administrative record.

    ``context`` holds a small number of scalar values that explain the decision, for
    example a reason category or a count. It is not a payload dump: sensitive field
    names are rejected outright rather than redacted, because an audit record should
    never have been asked to carry a secret in the first place.
    """

    action: str
    outcome: AuditOutcome
    actor: AuditActor
    occurred_at: datetime
    event_id: InternalId = field(default_factory=new_internal_id)
    target: AuditTarget | None = None
    scope: str | None = None
    reason_code: str | None = None
    correlation_id: str | None = None
    context: dict[str, AuditContextValue] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if not _ACTION_PATTERN.match(self.action):
            raise InvariantViolation(
                "audit action must be a dotted lowercase name such as 'users.approve'"
            )
        if self.occurred_at.tzinfo is None:
            raise InvariantViolation("audit events require a timezone-aware timestamp")
        if len(self.context) > _MAX_CONTEXT_ENTRIES:
            raise InvariantViolation("audit context carries too many entries")
        for key, value in self.context.items():
            if is_sensitive_key(key):
                raise InvariantViolation(f"audit context may not carry the sensitive field {key!r}")
            if isinstance(value, str) and len(value) > _MAX_CONTEXT_VALUE_LENGTH:
                raise InvariantViolation(
                    f"audit context value for {key!r} is too long to be a category"
                )


def record_audit_event(
    *,
    action: str,
    outcome: AuditOutcome,
    actor: AuditActor,
    occurred_at: datetime,
    target: AuditTarget | None = None,
    scope: str | None = None,
    reason_code: str | None = None,
    correlation_id: str | None = None,
    context: dict[str, AuditContextValue] | None = None,
) -> AuditEvent:
    """Construct an audit event.

    A thin keyword-only constructor, so call sites read as prose at the point where
    a security decision is made and cannot accidentally transpose positional
    arguments such as actor and target.
    """
    return AuditEvent(
        action=action,
        outcome=outcome,
        actor=actor,
        occurred_at=occurred_at,
        target=target,
        scope=scope,
        reason_code=reason_code,
        correlation_id=correlation_id,
        context=dict(context or {}),
    )
