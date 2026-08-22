"""Background task handlers.

Handlers live here and share the domain and application packages, exactly as ADR 0001
described. What changed under ADR 0002 is how they are invoked: there is no
always-running colocated process, and under ADR 0004 a handler is called by whatever
drains the durable dispatch table.

A handler takes a :class:`~learning_platform.application.tasks.registry.TaskContext`
and does its work. It does not own a main loop, a scheduler, a broker connection, or
a transaction it did not open. It imports ``application`` and ``domain`` only, never
infrastructure, which is what keeps it runnable under any delivery mechanism.

Every handler must be idempotent, must take only internal identifiers in its payload,
must not assume it runs in the same process or region as the request that dispatched
it, and must revalidate authorization when it acts on user-scoped content, because a
permission that held at dispatch may have been revoked before execution.

Only ``maintenance.verify_dispatch`` exists so far. Real handlers arrive with the
features that require them.
"""

from learning_platform.worker.registry import build_task_registry

__all__ = ["build_task_registry"]
