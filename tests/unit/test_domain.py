"""Domain identifiers, clock, and audit invariants."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

import pytest

from learning_platform.domain.audit import (
    AuditActor,
    AuditActorKind,
    AuditEvent,
    AuditOutcome,
    AuditTarget,
    record_audit_event,
)
from learning_platform.domain.clock import FixedClock, SystemClock
from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.identifiers import (
    ExternalId,
    new_internal_id,
    parse_internal_id,
)


class TestInternalIdentifiers:
    def test_generated_identifiers_are_uuid_version_7(self) -> None:
        assert new_internal_id().version == 7

    def test_identifiers_are_unique(self) -> None:
        assert len({new_internal_id() for _ in range(1000)}) == 1000

    def test_identifiers_are_time_ordered(self) -> None:
        """Version 7 orders by time, which is what makes it index well."""
        generated = [new_internal_id() for _ in range(50)]
        assert generated == sorted(generated, key=lambda value: value.hex)

    def test_a_well_formed_identifier_parses(self) -> None:
        original = new_internal_id()
        assert parse_internal_id(str(original)) == original

    @pytest.mark.parametrize("value", ["", "not-a-uuid", "12345", "'; DROP TABLE x;--"])
    def test_malformed_identifiers_are_rejected(self, value: str) -> None:
        with pytest.raises(ValueError):
            parse_internal_id(value)


class TestExternalIdentifiers:
    def test_provider_and_value_are_both_required(self) -> None:
        with pytest.raises(ValueError):
            ExternalId(provider="", value="abc")
        with pytest.raises(ValueError):
            ExternalId(provider="google", value="")

    def test_the_same_value_from_two_providers_is_not_equal(self) -> None:
        assert ExternalId("google", "1") != ExternalId("matrix", "1")

    def test_an_implausibly_long_value_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            ExternalId(provider="google", value="x" * 5000)

    def test_it_is_hashable_so_it_can_key_a_mapping(self) -> None:
        assert {ExternalId("google", "1"): "course"}[ExternalId("google", "1")] == "course"


class TestClock:
    def test_the_system_clock_returns_aware_utc(self) -> None:
        now = SystemClock().now()
        assert now.tzinfo is not None
        assert now.utcoffset() == timedelta(0)

    def test_a_fixed_clock_does_not_move(self) -> None:
        instant = datetime(2026, 8, 21, 12, 0, tzinfo=UTC)
        clock = FixedClock(instant)
        assert clock.now() == clock.now() == instant

    def test_a_naive_instant_is_rejected(self) -> None:
        with pytest.raises(ValueError):
            FixedClock(datetime(2026, 8, 21, 12, 0))


class TestAuditEvent:
    def _actor(self) -> AuditActor:
        return AuditActor(kind=AuditActorKind.USER, user_id=new_internal_id())

    def _event(self, **overrides: object) -> AuditEvent:
        values: dict[str, object] = {
            "action": "users.approve",
            "outcome": AuditOutcome.ALLOWED,
            "actor": self._actor(),
            "occurred_at": datetime.now(UTC),
        }
        values.update(overrides)
        return record_audit_event(**values)  # type: ignore[arg-type]

    def test_a_valid_event_is_created(self) -> None:
        event = self._event()
        assert event.action == "users.approve"
        assert event.event_id.version == 7

    def test_each_event_gets_its_own_identifier(self) -> None:
        assert self._event().event_id != self._event().event_id

    @pytest.mark.parametrize(
        "action", ["approve", "Users.Approve", "users approve", "users.", "", "users..x"]
    )
    def test_a_malformed_action_name_is_rejected(self, action: str) -> None:
        with pytest.raises(InvariantViolation, match="dotted lowercase"):
            self._event(action=action)

    def test_a_naive_timestamp_is_rejected(self) -> None:
        with pytest.raises(InvariantViolation, match="timezone-aware"):
            self._event(occurred_at=datetime(2026, 8, 21, 12, 0))

    def test_a_denied_outcome_is_recordable(self) -> None:
        """Refusals are exactly the events worth keeping."""
        assert self._event(outcome=AuditOutcome.DENIED).outcome is AuditOutcome.DENIED

    def test_a_failure_is_distinct_from_a_denial(self) -> None:
        """An integration outage must never be recorded as an authorization decision."""
        assert AuditOutcome.FAILED is not AuditOutcome.DENIED

    def test_sensitive_context_is_rejected_rather_than_redacted(self) -> None:
        with pytest.raises(InvariantViolation, match="sensitive"):
            self._event(context={"access_token": "ya29.abc"})

    def test_ordinary_context_is_kept(self) -> None:
        assert self._event(context={"reviewed_count": 3}).context == {"reviewed_count": 3}

    def test_an_over_long_context_value_is_rejected(self) -> None:
        with pytest.raises(InvariantViolation, match="too long"):
            self._event(context={"note": "x" * 500})

    def test_too_many_context_entries_are_rejected(self) -> None:
        with pytest.raises(InvariantViolation, match="too many"):
            self._event(context={f"field_{index}": index for index in range(50)})

    def test_an_event_is_immutable_once_created(self) -> None:
        with pytest.raises(AttributeError):
            self._event().action = "users.reject"  # type: ignore[misc]


class TestAuditActor:
    def test_a_user_actor_requires_an_identifier(self) -> None:
        with pytest.raises(InvariantViolation):
            AuditActor(kind=AuditActorKind.USER)

    @pytest.mark.parametrize(
        "kind", [AuditActorKind.SYSTEM, AuditActorKind.SERVICE, AuditActorKind.ANONYMOUS]
    )
    def test_a_non_user_actor_may_not_carry_a_user_identifier(self, kind: AuditActorKind) -> None:
        with pytest.raises(InvariantViolation):
            AuditActor(kind=kind, user_id=new_internal_id())

    def test_an_anonymous_actor_is_valid(self) -> None:
        """Unauthenticated attempts are audited too."""
        assert AuditActor(kind=AuditActorKind.ANONYMOUS).user_id is None


class TestAuditTarget:
    def test_a_target_requires_a_type(self) -> None:
        with pytest.raises(InvariantViolation):
            AuditTarget(target_type="")

    def test_a_target_may_omit_an_identifier(self) -> None:
        """Some actions target a collection rather than one record."""
        assert AuditTarget(target_type="application").target_id is None

    def test_a_target_accepts_an_internal_identifier(self) -> None:
        identifier = new_internal_id()
        target = AuditTarget(target_type="resource", target_id=identifier)
        assert isinstance(target.target_id, uuid.UUID)
