"""The rules a task obeys, independent of how it is delivered.

These pin ADR 0004's domain half: what a task type and payload may be, which state
changes are legal, and when a retry becomes due. None of it touches a database, a
queue, or HTTP, which is the point: swapping the delivery runtime must not be able to
change any of it.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from learning_platform.domain.errors import InvariantViolation
from learning_platform.domain.tasks import (
    ALLOWED_TRANSITIONS,
    MAX_PAYLOAD_ENTRIES,
    RetryPolicy,
    TaskFailed,
    TaskFailureKind,
    TaskState,
    TaskType,
    ensure_transition,
    validate_error_code,
    validate_task_payload,
)

NOW = datetime(2026, 8, 23, 12, 0, tzinfo=UTC)


class TestTaskType:
    @pytest.mark.parametrize(
        "name",
        [
            "classroom.sync_course",
            "search.index_resource",
            "archive.build.manifest",
            "maintenance.verify_dispatch",
        ],
    )
    def test_dotted_lowercase_names_are_accepted(self, name: str) -> None:
        assert str(TaskType(name)) == name

    @pytest.mark.parametrize(
        "name",
        [
            "sync",
            "Classroom.Sync",
            "classroom sync",
            "",
            ".leading",
            "trailing.",
            "has-a-hyphen.x",
        ],
    )
    def test_other_shapes_are_rejected(self, name: str) -> None:
        with pytest.raises(InvariantViolation):
            TaskType(name)

    @pytest.mark.parametrize(
        "name",
        [
            "learning_platform.worker.maintenance:verify",
            "os.system",
            "builtins.eval",
        ],
    )
    def test_a_name_shaped_like_code_is_still_only_a_name(self, name: str) -> None:
        """Some import-like strings match the pattern, and that is harmless.

        The type is a lookup key, never something resolved to a module or callable.
        Nothing anywhere imports by task type, so a plausible-looking one selects no
        code: the registry either has it or refuses it.
        """
        if ":" in name:
            with pytest.raises(InvariantViolation):
                TaskType(name)
        else:
            assert str(TaskType(name)) == name


class TestStateMachine:
    def test_every_state_has_a_transition_rule(self) -> None:
        """A state missing from the table would raise a KeyError at runtime."""
        assert set(ALLOWED_TRANSITIONS) == set(TaskState)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskState.PENDING, TaskState.CLAIMED),
            (TaskState.PENDING, TaskState.CANCELLED),
            (TaskState.CLAIMED, TaskState.SUCCEEDED),
            (TaskState.CLAIMED, TaskState.FAILED),
            (TaskState.CLAIMED, TaskState.EXHAUSTED),
            (TaskState.CLAIMED, TaskState.PENDING),
            (TaskState.CLAIMED, TaskState.CANCELLED),
        ],
    )
    def test_legal_transitions_are_permitted(self, current: TaskState, target: TaskState) -> None:
        ensure_transition(current, target)

    @pytest.mark.parametrize(
        ("current", "target"),
        [
            (TaskState.PENDING, TaskState.SUCCEEDED),
            (TaskState.PENDING, TaskState.PENDING),
            (TaskState.SUCCEEDED, TaskState.PENDING),
            (TaskState.SUCCEEDED, TaskState.SUCCEEDED),
            (TaskState.FAILED, TaskState.CLAIMED),
            (TaskState.EXHAUSTED, TaskState.PENDING),
            (TaskState.CANCELLED, TaskState.CLAIMED),
        ],
    )
    def test_illegal_transitions_are_refused(self, current: TaskState, target: TaskState) -> None:
        with pytest.raises(InvariantViolation):
            ensure_transition(current, target)

    def test_a_task_cannot_skip_being_claimed(self) -> None:
        """Succeeding without a claim would mean work ran without a lease."""
        with pytest.raises(InvariantViolation):
            ensure_transition(TaskState.PENDING, TaskState.SUCCEEDED)

    def test_completing_twice_is_refused(self) -> None:
        """Two runners believing they own one row is a defect, not a duplicate.

        At-least-once delivery makes duplicate *execution* expected and safe. A
        duplicate *completion* is different: it means the lease failed to do its job,
        and tolerating it would hide that.
        """
        with pytest.raises(InvariantViolation):
            ensure_transition(TaskState.SUCCEEDED, TaskState.SUCCEEDED)

    @pytest.mark.parametrize(
        "state",
        [TaskState.SUCCEEDED, TaskState.FAILED, TaskState.EXHAUSTED, TaskState.CANCELLED],
    )
    def test_terminal_states_have_no_way_out(self, state: TaskState) -> None:
        assert state.is_terminal is True
        assert ALLOWED_TRANSITIONS[state] == frozenset()

    @pytest.mark.parametrize("state", [TaskState.PENDING, TaskState.CLAIMED])
    def test_active_states_are_not_terminal(self, state: TaskState) -> None:
        assert state.is_terminal is False


class TestFailureClassification:
    @pytest.mark.parametrize("kind", [TaskFailureKind.INFRASTRUCTURE, TaskFailureKind.PROVIDER])
    def test_transient_failures_are_retryable(self, kind: TaskFailureKind) -> None:
        assert kind.is_retryable is True

    @pytest.mark.parametrize(
        "kind",
        [TaskFailureKind.INVALID_PAYLOAD, TaskFailureKind.AUTHORIZATION_INVALIDATED],
    )
    def test_permanent_failures_are_not_retryable(self, kind: TaskFailureKind) -> None:
        """Retrying either would fail identically, so it would only waste attempts."""
        assert kind.is_retryable is False

    def test_a_revoked_permission_is_never_retried(self) -> None:
        """A grant that has gone away does not come back by waiting."""
        assert TaskFailureKind.AUTHORIZATION_INVALIDATED.is_retryable is False

    def test_a_failure_carries_a_code_and_a_kind(self) -> None:
        failure = TaskFailed(TaskFailureKind.PROVIDER, "provider_timeout")
        assert failure.kind is TaskFailureKind.PROVIDER
        assert failure.code == "provider_timeout"

    def test_a_failure_is_not_a_domain_error(self) -> None:
        """DomainError messages reach HTTP responses. This one never should."""
        from learning_platform.domain.errors import DomainError

        assert not isinstance(TaskFailed(TaskFailureKind.PROVIDER, "x_y"), DomainError)


class TestErrorCodes:
    @pytest.mark.parametrize("code", ["provider_timeout", "unknown_task_type", "a"])
    def test_short_slugs_are_accepted(self, code: str) -> None:
        assert validate_error_code(code) == code

    def test_a_code_is_normalised(self) -> None:
        assert validate_error_code("  Provider_Timeout  ") == "provider_timeout"

    @pytest.mark.parametrize(
        "code",
        [
            "",
            "Connection refused to 10.0.0.5:5432",
            "password=hunter2",
            "a" * 64,
            "has spaces",
            "1_starts_with_a_digit",
        ],
    )
    def test_anything_message_shaped_is_refused(self, code: str) -> None:
        """The column must not become a place exception text ends up."""
        with pytest.raises(InvariantViolation):
            validate_error_code(code)

    def test_a_failure_refuses_a_message_as_its_code(self) -> None:
        with pytest.raises(InvariantViolation):
            TaskFailed(TaskFailureKind.PROVIDER, "could not connect to db.internal:5432")


class TestPayloadValidation:
    def test_an_ordinary_payload_of_identifiers_passes(self) -> None:
        validate_task_payload({"course_id": "0198f0", "revision": 4, "force": False})

    def test_an_empty_payload_passes(self) -> None:
        validate_task_payload({})

    @pytest.mark.parametrize(
        "key",
        [
            "access_token",
            "refresh_token",
            "password",
            "private_key",
            "cookie",
            "client_secret",
            "recovery_key",
            "plaintext",
            "signed_url",
        ],
    )
    def test_a_sensitive_field_name_is_refused(self, key: str) -> None:
        """A payload is written to durable storage and crosses a process boundary."""
        with pytest.raises(InvariantViolation, match="sensitive"):
            validate_task_payload({key: "value"})

    def test_a_nested_object_is_refused(self) -> None:
        """Nesting means an entity graph, which is a stale copy of the database."""
        with pytest.raises(InvariantViolation, match="scalar"):
            validate_task_payload({"course": {"id": "x"}})  # type: ignore[dict-item]

    def test_a_list_is_refused(self) -> None:
        with pytest.raises(InvariantViolation, match="scalar"):
            validate_task_payload({"ids": ["a", "b"]})  # type: ignore[dict-item]

    def test_too_many_fields_are_refused(self) -> None:
        payload = {f"field_{index}": index for index in range(MAX_PAYLOAD_ENTRIES + 1)}
        with pytest.raises(InvariantViolation, match="at most"):
            validate_task_payload(payload)

    def test_a_field_at_the_limit_is_accepted(self) -> None:
        validate_task_payload({f"field_{index}": index for index in range(MAX_PAYLOAD_ENTRIES)})

    def test_an_oversized_string_is_refused(self) -> None:
        """An identifier is short. Anything long is a document in disguise."""
        with pytest.raises(InvariantViolation, match="too long"):
            validate_task_payload({"note": "x" * 513})

    def test_a_boolean_is_accepted_as_a_scalar(self) -> None:
        """bool subclasses int, so a naive type check would have let it through by
        accident rather than by decision."""
        validate_task_payload({"force": True})


class TestRetryPolicy:
    def test_backoff_grows_exponentially(self) -> None:
        policy = RetryPolicy(base_delay_seconds=30, max_delay_seconds=3600)
        delays = [
            policy.next_attempt_at(attempt=attempt, now=NOW) - NOW for attempt in (1, 2, 3, 4)
        ]
        assert delays == [
            timedelta(seconds=30),
            timedelta(seconds=60),
            timedelta(seconds=120),
            timedelta(seconds=240),
        ]

    def test_backoff_is_capped(self) -> None:
        """Otherwise a long-failing task drifts to a retry time beyond its retention."""
        policy = RetryPolicy(base_delay_seconds=30, max_delay_seconds=300)
        assert policy.next_attempt_at(attempt=20, now=NOW) == NOW + timedelta(seconds=300)

    def test_a_huge_attempt_count_does_not_overflow_into_a_giant_delay(self) -> None:
        policy = RetryPolicy(base_delay_seconds=30, max_delay_seconds=3600)
        assert policy.next_attempt_at(attempt=10_000, now=NOW) == NOW + timedelta(seconds=3600)

    def test_attempt_numbering_starts_at_one(self) -> None:
        with pytest.raises(InvariantViolation):
            RetryPolicy().next_attempt_at(attempt=0, now=NOW)

    def test_attempts_run_out(self) -> None:
        policy = RetryPolicy(max_attempts=3)
        assert policy.has_attempts_remaining(attempt=2) is True
        assert policy.has_attempts_remaining(attempt=3) is False

    def test_a_task_keeps_the_budget_it_was_dispatched_with(self) -> None:
        """Changing the deployment default must not re-open an exhausted task."""
        policy = RetryPolicy(max_attempts=10)
        assert policy.has_attempts_remaining(attempt=2, max_attempts=2) is False

    @pytest.mark.parametrize(
        "kwargs",
        [
            {"max_attempts": 0},
            {"base_delay_seconds": 0},
            {"base_delay_seconds": 100, "max_delay_seconds": 10},
        ],
    )
    def test_an_incoherent_policy_is_refused(self, kwargs: dict[str, int]) -> None:
        with pytest.raises(InvariantViolation):
            RetryPolicy(**kwargs)

    def test_retries_are_always_bounded(self) -> None:
        """There is no configuration that means 'retry for ever'."""
        with pytest.raises(InvariantViolation):
            RetryPolicy(max_attempts=0)
