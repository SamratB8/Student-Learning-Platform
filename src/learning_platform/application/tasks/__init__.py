"""Background work orchestration: what runs, and what happens when it does not.

The registry decides which task types exist and which payload versions each can read.
The runner claims due work, executes it, and records the outcome under the domain's
state machine. Neither knows how a task was delivered, which is what keeps ADR 0004's
runtime choice replaceable.
"""

from learning_platform.application.tasks.registry import (
    TaskContext,
    TaskHandler,
    TaskRegistry,
)
from learning_platform.application.tasks.runner import (
    DrainReport,
    TaskObserver,
    TaskRunner,
    TaskUnitOfWork,
)

__all__ = [
    "DrainReport",
    "TaskContext",
    "TaskHandler",
    "TaskObserver",
    "TaskRegistry",
    "TaskRunner",
    "TaskUnitOfWork",
]
