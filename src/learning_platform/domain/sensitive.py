"""Which field names must never be recorded.

SECURITY_MODEL.md forbids passwords, OAuth codes and tokens, cookies, private keys,
message plaintext, signed URLs, and full sensitive payloads from reaching logs or
audit records. That is a policy statement, so it lives in the domain, and both the
logging pipeline and the audit sink apply the same rule.

The match is deliberately broad. A false positive costs one redacted debugging
field; a false negative writes a credential to durable storage.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Final

__all__ = ["REDACTED", "is_sensitive_key", "redact_mapping"]

REDACTED: Final = "[redacted]"

_SENSITIVE_KEY_PATTERN: Final = re.compile(
    r"""
    (?:^|_|\.|-)                # start of the name or a word boundary
    (?:
        pass(?:word|phrase)?
      | secret
      | token
      | credentials?
      | api[_-]?key
      | private[_-]?key
      | signing[_-]?key
      | session[_-]?key
      | access[_-]?key
      | refresh
      | authorization
      | auth[_-]?code
      | cookie
      | otp
      | signature
      | signed[_-]?url
      | plaintext
      | ciphertext
      | recovery[_-]?key
      | client[_-]?secret
    )
    (?:$|_|\.|-|s$)
    """,
    re.IGNORECASE | re.VERBOSE,
)

# Whole names that are sensitive but do not carry a distinguishing word boundary.
_SENSITIVE_EXACT: Final[frozenset[str]] = frozenset(
    {
        "authorization",
        "cookie",
        "set-cookie",
        "key",
        "keys",
        "pwd",
        "sig",
    }
)


def is_sensitive_key(key: str) -> bool:
    """Return whether a field name must be redacted rather than recorded."""
    normalized = key.strip().lower()
    if normalized in _SENSITIVE_EXACT:
        return True
    return _SENSITIVE_KEY_PATTERN.search(normalized) is not None


def redact_mapping(values: Mapping[str, object]) -> dict[str, object]:
    """Return a copy with sensitive values replaced, recursing into nested mappings.

    Only the value is replaced. The key survives, because knowing that a token was
    present is useful and the name itself is not the secret.

    Accepts any ``Mapping`` rather than ``dict`` so a caller's narrower mapping type,
    such as ``dict[str, str]``, is not rejected by dict's invariance.
    """
    redacted: dict[str, object] = {}
    for key, value in values.items():
        if is_sensitive_key(key):
            redacted[key] = REDACTED
        elif isinstance(value, Mapping):
            redacted[key] = redact_mapping(value)
        else:
            redacted[key] = value
    return redacted
