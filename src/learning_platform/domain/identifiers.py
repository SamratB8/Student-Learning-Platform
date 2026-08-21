"""Internal and external identifier types.

DATA_MODEL.md requires generated internal IDs, with provider identifiers kept as
typed external values that are never primary business keys.

Internal IDs are UUID version 7: time-ordered, so they cluster well in an index,
without exposing a countable row order the way a sequence does. Generating them in
the application also means an entity has its identity before it is ever persisted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Final, NewType

__all__ = [
    "ExternalId",
    "InternalId",
    "new_internal_id",
    "parse_internal_id",
]

InternalId = NewType("InternalId", uuid.UUID)

_MAX_EXTERNAL_ID_LENGTH: Final = 512


def new_internal_id() -> InternalId:
    """Generate a fresh time-ordered internal identifier."""
    return InternalId(uuid.uuid7())


def parse_internal_id(value: str) -> InternalId:
    """Parse an internal identifier supplied from outside the application.

    Raises:
        ValueError: if the value is not a well-formed UUID.

    Parsing succeeding says nothing about authorization. The caller must still
    look the identifier up under the requesting principal's scope.
    """
    return InternalId(uuid.UUID(value))


@dataclass(frozen=True, slots=True)
class ExternalId:
    """An identifier owned by an external provider.

    Kept distinct from :data:`InternalId` so a provider-supplied value can never be
    passed where an internal identifier is expected. ``provider`` is part of the
    value because the same string may be meaningful to two providers at once.
    """

    provider: str
    value: str

    def __post_init__(self) -> None:
        if not self.provider:
            raise ValueError("external identifier requires a provider")
        if not self.value:
            raise ValueError("external identifier requires a value")
        if len(self.value) > _MAX_EXTERNAL_ID_LENGTH:
            raise ValueError("external identifier value is implausibly long")

    def __str__(self) -> str:
        return f"{self.provider}:{self.value}"
