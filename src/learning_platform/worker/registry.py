"""Where every task type this deployment can run is declared.

One function, called once during composition. Registration is explicit and central on
purpose: the alternative, a decorator that registers on import, makes the set of
runnable task types depend on which modules happened to be imported, which is both a
security property and a debugging problem nobody should have to reconstruct.

A feature that needs background work adds its handler module and one line here.
"""

from __future__ import annotations

from learning_platform.application.tasks.registry import TaskRegistry
from learning_platform.worker.maintenance import register_maintenance_tasks

__all__ = ["build_task_registry"]


def build_task_registry() -> TaskRegistry:
    """Return the registry of task types this deployment can execute."""
    registry = TaskRegistry()
    register_maintenance_tasks(registry)
    return registry
