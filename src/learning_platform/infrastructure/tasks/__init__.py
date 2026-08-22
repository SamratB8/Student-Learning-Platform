"""Durable background work: storage, dispatch, and observation.

ADR 0004 makes the ``task_dispatch`` table the system of record and treats delivery
as a replaceable adapter. What lives here is the storage side and the two dispatcher
implementations; the code that decides *when* a drain happens is deployment
configuration, not application code.
"""

from learning_platform.infrastructure.tasks.inline import InlineTaskDispatcher
from learning_platform.infrastructure.tasks.models import TaskDispatchRecord
from learning_platform.infrastructure.tasks.observer import LoggingTaskObserver
from learning_platform.infrastructure.tasks.outbox import OutboxTaskDispatcher
from learning_platform.infrastructure.tasks.repository import SqlAlchemyTaskDispatchStore

__all__ = [
    "InlineTaskDispatcher",
    "LoggingTaskObserver",
    "OutboxTaskDispatcher",
    "SqlAlchemyTaskDispatchStore",
    "TaskDispatchRecord",
]
