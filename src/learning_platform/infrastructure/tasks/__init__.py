"""Task dispatch implementations. See ADR 0004, which is still open."""

from learning_platform.infrastructure.tasks.inline import InlineTaskDispatcher

__all__ = ["InlineTaskDispatcher"]
