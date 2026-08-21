"""Hosting detection and the fail-closed environment rule.

The invariant this module exists to enforce:

    A hosted deployment may never silently fall back to development mode.

``APP_ENV`` has a development default, which is right on a developer's machine and
dangerous anywhere else. A real Vercel deployment went live with no ``APP_ENV`` set,
fell back to that default, and served publicly with development error verbosity,
non-secure session cookie settings, and a ``/readyz`` that falsely reported ready.
Nothing failed, which is precisely the problem: the weakest posture was also the
quietest one.

The rule below removes the silent path. When execution is hosted, the environment is
either stated explicitly, derived from trusted platform metadata, or startup fails.

Trust boundary
--------------

Only server-side environment variables set by the platform are consulted. Request
headers are never read here, and cannot be: this runs once at startup, before any
request exists. ``VERCEL_ENV`` is the signal used because its value set is closed
(``production``, ``preview``, ``development``). ``VERCEL_TARGET_ENV`` is deliberately
not used for the safety decision, because it may hold an arbitrary custom environment
name and so cannot be validated against a known set.
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from typing import Final

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.environments import AppEnvironment

__all__ = [
    "VERCEL_MARKER_VARIABLES",
    "HostingPlatform",
    "detect_platform",
    "resolve_app_environment",
]

# Any of these appearing in the environment means Vercel is running this process.
# Several are listed rather than only ``VERCEL`` because that one is documented as an
# indicator that system environment variables have been *exposed*, which is a project
# setting that can be turned off. Requiring all of them would fail open the moment one
# is withheld; requiring any of them fails closed instead.
VERCEL_MARKER_VARIABLES: Final[tuple[str, ...]] = (
    "VERCEL",
    "VERCEL_ENV",
    "VERCEL_URL",
    "VERCEL_REGION",
    "VERCEL_DEPLOYMENT_ID",
    "VERCEL_PROJECT_ID",
    "VERCEL_TARGET_ENV",
)

# Vercel's own environment names, mapped to this application's vocabulary.
#
# ``preview`` maps to STAGING rather than to a preview-specific environment because
# STAGING already carries production strictness: secure cookies, HSTS, JSON logs, no
# debug output, and the full required-configuration check. A preview is reachable over
# the internet, so it is treated as a deployment, not as a developer's machine.
#
# ``development`` is what ``vercel dev`` reports while running on a developer's own
# machine. It is an explicit statement by the platform, not a fallback, so honouring
# it does not reopen the hole this module closes.
_VERCEL_ENVIRONMENTS: Final[Mapping[str, AppEnvironment]] = {
    "production": AppEnvironment.PRODUCTION,
    "preview": AppEnvironment.STAGING,
    "development": AppEnvironment.DEVELOPMENT,
}


class HostingPlatform(StrEnum):
    """Where this process is running."""

    LOCAL = "local"
    """A developer's machine, or a test run. Not reachable from the internet."""

    VERCEL = "vercel"
    """A Vercel build or function invocation."""


def detect_platform(environ: Mapping[str, str]) -> HostingPlatform:
    """Identify the hosting platform from server-side environment variables only."""
    for marker in VERCEL_MARKER_VARIABLES:
        if environ.get(marker, "").strip():
            return HostingPlatform.VERCEL
    return HostingPlatform.LOCAL


def _explicit_app_environment(environ: Mapping[str, str]) -> AppEnvironment | None:
    """Parse ``APP_ENV`` when it is set to a non-empty value.

    Raises:
        ConfigurationError: if it is set to something that is not a known environment.

    The rejected value is not echoed, matching the rule that configuration errors name
    variables rather than repeat their contents.
    """
    raw = environ.get("APP_ENV", "").strip()
    if not raw:
        return None
    try:
        return AppEnvironment(raw.lower())
    except ValueError:
        raise ConfigurationError(
            "APP_ENV is not a recognised environment; expected one of "
            f"{sorted(member.value for member in AppEnvironment)}"
        ) from None


def resolve_app_environment(
    environ: Mapping[str, str], *, assume_hosted: bool = False
) -> AppEnvironment:
    """Decide which application environment this process is running as.

    Args:
        environ: server-side environment variables, normally ``os.environ``.
        assume_hosted: treat this process as hosted even when no platform marker is
            present. The hosting entry point passes this, because being loaded at all
            proves a platform loaded it. It closes the case where a project has
            system environment variables switched off and therefore exposes no marker.

    Raises:
        ConfigurationError: if the environment is hosted and cannot be determined
            unambiguously, or if ``APP_ENV`` names an environment that is not valid
            for a hosted deployment.

    The rule, in order:

    1. Not hosted: use ``APP_ENV`` if set, otherwise development. Unchanged local
       behaviour, so Windows-native development is not affected.
    2. Hosted and the platform reports ``development`` (``vercel dev``): this runs on
       a developer's machine, so use ``APP_ENV`` if set, otherwise development.
    3. Hosted and the platform reports ``production`` or ``preview``: an explicit
       ``APP_ENV`` wins but must be a deployed environment; otherwise the platform's
       value is mapped. Development and test are refused outright here.
    4. Hosted but the platform reports nothing recognisable: accept only an explicit,
       deployed ``APP_ENV``. Otherwise fail.
    """
    platform = HostingPlatform.VERCEL if assume_hosted else detect_platform(environ)
    explicit = _explicit_app_environment(environ)

    if platform is HostingPlatform.LOCAL:
        return explicit or AppEnvironment.DEVELOPMENT

    reported = environ.get("VERCEL_ENV", "").strip().lower()
    platform_environment = _VERCEL_ENVIRONMENTS.get(reported)

    # `vercel dev`: hosted tooling, but executing locally.
    if platform_environment is AppEnvironment.DEVELOPMENT:
        return explicit or AppEnvironment.DEVELOPMENT

    if explicit is not None:
        if not explicit.is_deployed:
            raise ConfigurationError(
                f"APP_ENV is set to {explicit.value!r}, which is only valid on a "
                "developer's machine. A hosted deployment must run as "
                "'staging' or 'production'."
            )
        return explicit

    if platform_environment is not None:
        return platform_environment

    raise ConfigurationError(
        "This process is running on a hosted platform but its environment could not "
        "be determined: VERCEL_ENV is missing or unrecognised. Set APP_ENV explicitly "
        "to 'staging' or 'production' for this deployment, or enable access to system "
        "environment variables for the project. Refusing to start rather than "
        "defaulting to development."
    )
