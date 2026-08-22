"""Time access as an explicit dependency.

Domain and application code must not call :func:`datetime.now` directly. Taking a
clock as a dependency keeps time-dependent policy testable without patching module
globals, and makes it obvious that every stored timestamp is timezone-aware UTC.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol

__all__ = ["Clock", "FixedClock", "SystemClock"]


class Clock(Protocol):
    """Supplies the current instant."""

    def now(self) -> datetime:
        """Return the current time as a timezone-aware UTC datetime."""
        ...


class SystemClock:
    """The real clock."""

    def now(self) -> datetime:
        return datetime.now(UTC)


class FixedClock:
    """A clock frozen at a chosen instant, for tests."""

    def __init__(self, instant: datetime) -> None:
        if instant.tzinfo is None:
            raise ValueError("fixed clock requires a timezone-aware instant")
        self._instant = instant.astimezone(UTC)

    def now(self) -> datetime:
        return self._instant
