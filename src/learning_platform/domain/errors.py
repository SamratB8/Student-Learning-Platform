"""Domain error hierarchy.

Errors carry a machine-readable ``code`` and a message that is safe to show a user.
Anything sensitive belongs in structured log context, never in the message, because
these messages reach HTTP responses.
"""

from __future__ import annotations

__all__ = [
    "AuthorizationDenied",
    "ConfigurationError",
    "DomainError",
    "InvariantViolation",
    "NotFound",
    "ValidationFailed",
]


class DomainError(Exception):
    """Base class for expected, domain-meaningful failures."""

    code = "domain_error"
    message = "The request could not be completed."

    def __init__(self, message: str | None = None) -> None:
        if message is not None:
            self.message = message
        super().__init__(self.message)


class ValidationFailed(DomainError):
    """Input did not satisfy a domain rule."""

    code = "validation_failed"
    message = "The submitted data is not valid."


class NotFound(DomainError):
    """The requested entity does not exist, or is not visible to this principal.

    Deliberately indistinguishable from a denial in responses, so that probing for
    identifiers cannot reveal whether a record exists.
    """

    code = "not_found"
    message = "The requested item could not be found."


class AuthorizationDenied(DomainError):
    """The principal may not perform this action.

    Authorization denies by default. This error is raised on an explicit denial and
    on any evaluation that could not complete: an integration failure must never
    fail authorization open.
    """

    code = "authorization_denied"
    message = "You do not have permission to perform this action."


class InvariantViolation(DomainError):
    """A domain invariant would be broken. This indicates a defect, not user error."""

    code = "invariant_violation"
    message = "The request would leave the system in an invalid state."


class ConfigurationError(DomainError):
    """Deployment configuration is missing or unusable.

    Raised at startup so a misconfigured environment fails fast and loudly rather
    than serving requests with unsafe defaults.
    """

    code = "configuration_error"
    message = "The application is not configured correctly."
