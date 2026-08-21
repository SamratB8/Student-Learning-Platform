"""The application environment enum.

Kept in its own module so that both :mod:`settings` and :mod:`hosting` can import it
without a cycle: ``settings`` depends on ``hosting`` to resolve the environment, and
``hosting`` needs the enum to express what it resolved to.
"""

from __future__ import annotations

from enum import StrEnum

__all__ = ["AppEnvironment"]


class AppEnvironment(StrEnum):
    """Which deployment environment this process is running as."""

    DEVELOPMENT = "development"
    TEST = "test"
    STAGING = "staging"
    PRODUCTION = "production"

    @property
    def is_deployed(self) -> bool:
        """Whether this environment is exposed beyond a developer's machine.

        Staging is treated with production's strictness on purpose: a staging
        environment holds real configuration and is reachable over the network.
        """
        return self in {AppEnvironment.STAGING, AppEnvironment.PRODUCTION}
