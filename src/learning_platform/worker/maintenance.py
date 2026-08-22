"""The one task type Phase 1B ships.

``maintenance.verify_dispatch`` does nothing at all, and that is the point. Its value
is entirely in the fact that it *ran*: a use case dispatched it inside a transaction,
the transaction committed, a scheduled invocation claimed it, the registry resolved
it, the handler was called, and the outcome was recorded. Anything the handler did
itself would only add ways for the test to fail for unrelated reasons.

The evidence is the runner's own ``task.started`` and ``task.finished`` log lines and
the row's terminal state, so the handler needs no logging of its own. That also keeps
this module inside the layer rule: handlers import ``application`` and ``domain``,
never infrastructure, which is what lets the same handler run under any delivery
mechanism ADR 0004 might later select.

It exists because "is background processing actually working in this deployment"
otherwise has no answer until a real feature depends on it, which is the worst
possible moment to find out. It is infrastructure, not a product feature, and it is
deliberately the only handler here: real task types arrive with the features that
need them.
"""

from __future__ import annotations

from learning_platform.application.tasks.registry import TaskContext, TaskRegistry
from learning_platform.domain.tasks import TaskType

__all__ = ["VERIFY_DISPATCH", "register_maintenance_tasks", "verify_dispatch"]

VERIFY_DISPATCH = TaskType("maintenance.verify_dispatch")


def verify_dispatch(context: TaskContext) -> None:
    """Succeed, having changed nothing.

    Idempotent in the strongest available sense: it has no effect, so running it
    twice is indistinguishable from running it once. Every real handler has to earn
    that property deliberately; this one has it for free.
    """
    return None


def register_maintenance_tasks(registry: TaskRegistry) -> None:
    """Register the maintenance handlers on ``registry``."""
    registry.register(VERIFY_DISPATCH, verify_dispatch, payload_versions=(1,))
