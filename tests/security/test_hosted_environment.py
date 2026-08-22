"""A hosted deployment may never silently fall back to development mode.

The defect these tests pin was real, not hypothetical. A Vercel deployment went live
with no ``APP_ENV`` set, fell back to the development default, and served a public URL
with development error verbosity, non-secure session cookie settings, and a
``/readyz`` that answered 200 "ready" while nothing was configured. Nothing failed,
which is what made it dangerous.

The environment is read only from server-side variables at startup. Request headers
are never consulted and cannot be: resolution happens before any request exists.
"""

from __future__ import annotations

from typing import ClassVar

import pytest

from learning_platform.domain.errors import ConfigurationError
from learning_platform.infrastructure.config.environments import AppEnvironment
from learning_platform.infrastructure.config.hosting import (
    HostingPlatform,
    detect_platform,
    resolve_app_environment,
)

# A Vercel function invocation exposes these. Only the pieces the rule reads are
# modelled; the rest are irrelevant to the decision.
VERCEL_PRODUCTION = {"VERCEL": "1", "VERCEL_ENV": "production"}
VERCEL_PREVIEW = {"VERCEL": "1", "VERCEL_ENV": "preview"}
VERCEL_DEV_COMMAND = {"VERCEL": "1", "VERCEL_ENV": "development"}


class TestPlatformDetection:
    def test_an_empty_environment_is_local(self) -> None:
        assert detect_platform({}) is HostingPlatform.LOCAL

    def test_ordinary_local_variables_do_not_imply_hosting(self) -> None:
        environ = {"PATH": "/usr/bin", "HOME": "/home/dev", "APP_ENV": "development"}
        assert detect_platform(environ) is HostingPlatform.LOCAL

    @pytest.mark.parametrize(
        "marker",
        [
            "VERCEL",
            "VERCEL_ENV",
            "VERCEL_URL",
            "VERCEL_REGION",
            "VERCEL_DEPLOYMENT_ID",
            "VERCEL_PROJECT_ID",
            "VERCEL_TARGET_ENV",
        ],
    )
    def test_any_single_marker_is_enough(self, marker: str) -> None:
        """Requiring all of them would fail open the moment one was withheld."""
        assert detect_platform({marker: "production"}) is HostingPlatform.VERCEL

    def test_an_empty_marker_value_does_not_count(self) -> None:
        assert detect_platform({"VERCEL": "", "VERCEL_ENV": "  "}) is HostingPlatform.LOCAL


class TestLocalExecutionIsUnchanged:
    """Windows-native development must not be made harder by this rule."""

    def test_no_markers_and_no_app_env_is_development(self) -> None:
        assert resolve_app_environment({}) is AppEnvironment.DEVELOPMENT

    def test_an_explicit_local_environment_is_honoured(self) -> None:
        assert resolve_app_environment({"APP_ENV": "test"}) is AppEnvironment.TEST

    def test_a_developer_may_still_run_as_staging_locally(self) -> None:
        assert resolve_app_environment({"APP_ENV": "staging"}) is AppEnvironment.STAGING


class TestHostedWithoutAppEnv:
    """The exact situation that caused the incident."""

    def test_vercel_production_never_becomes_development(self) -> None:
        resolved = resolve_app_environment(VERCEL_PRODUCTION)
        assert resolved is AppEnvironment.PRODUCTION
        assert resolved is not AppEnvironment.DEVELOPMENT
        assert resolved.is_deployed is True

    def test_vercel_preview_never_becomes_development(self) -> None:
        resolved = resolve_app_environment(VERCEL_PREVIEW)
        assert resolved is AppEnvironment.STAGING
        assert resolved is not AppEnvironment.DEVELOPMENT
        assert resolved.is_deployed is True

    @pytest.mark.parametrize("environ", [VERCEL_PRODUCTION, VERCEL_PREVIEW])
    def test_the_result_always_carries_deployed_strictness(self, environ: dict[str, str]) -> None:
        """is_deployed drives secure cookies, HSTS, JSON logs, and no debug output."""
        assert resolve_app_environment(environ).is_deployed is True


class TestHostedWithExplicitAppEnv:
    def test_an_explicit_deployed_environment_is_accepted(self) -> None:
        environ = VERCEL_PREVIEW | {"APP_ENV": "staging"}
        assert resolve_app_environment(environ) is AppEnvironment.STAGING

    def test_an_explicit_production_on_a_preview_is_accepted(self) -> None:
        """Deliberate and still strict, so there is no reason to refuse it."""
        environ = VERCEL_PREVIEW | {"APP_ENV": "production"}
        assert resolve_app_environment(environ) is AppEnvironment.PRODUCTION

    @pytest.mark.parametrize("unsafe", ["development", "test"])
    @pytest.mark.parametrize("environ", [VERCEL_PRODUCTION, VERCEL_PREVIEW])
    def test_a_local_only_environment_is_refused_when_hosted(
        self, environ: dict[str, str], unsafe: str
    ) -> None:
        """Even stated deliberately, development mode on a public URL is refused."""
        with pytest.raises(ConfigurationError, match="developer"):
            resolve_app_environment(environ | {"APP_ENV": unsafe})

    def test_an_unrecognised_app_env_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="APP_ENV"):
            resolve_app_environment(VERCEL_PREVIEW | {"APP_ENV": "prod"})

    def test_an_unrecognised_app_env_is_refused_locally_too(self) -> None:
        with pytest.raises(ConfigurationError, match="APP_ENV"):
            resolve_app_environment({"APP_ENV": "prod"})


class TestAmbiguousHostedState:
    """Hosted but unidentifiable must fail closed."""

    def test_markers_without_a_reported_environment_fail(self) -> None:
        with pytest.raises(ConfigurationError, match="could not"):
            resolve_app_environment({"VERCEL_URL": "example.vercel.app"})

    def test_an_unrecognised_reported_environment_fails(self) -> None:
        with pytest.raises(ConfigurationError, match="could not"):
            resolve_app_environment({"VERCEL": "1", "VERCEL_ENV": "somethingelse"})

    def test_an_explicit_deployed_app_env_rescues_an_ambiguous_state(self) -> None:
        environ = {"VERCEL_URL": "example.vercel.app", "APP_ENV": "staging"}
        assert resolve_app_environment(environ) is AppEnvironment.STAGING

    def test_an_ambiguous_state_still_refuses_development(self) -> None:
        environ = {"VERCEL_URL": "example.vercel.app", "APP_ENV": "development"}
        with pytest.raises(ConfigurationError, match="developer"):
            resolve_app_environment(environ)

    def test_the_failure_names_what_to_fix(self) -> None:
        with pytest.raises(ConfigurationError) as error:
            resolve_app_environment({"VERCEL": "1"})
        message = str(error.value)
        assert "APP_ENV" in message
        assert "VERCEL_ENV" in message


class TestAssumeHosted:
    """The entry-point assertion, which does not depend on any marker existing.

    Every Vercel marker is gated behind a project setting that exposes system
    environment variables. With it switched off a deployment would look local.
    """

    def test_no_markers_at_all_still_refuses_to_default(self) -> None:
        with pytest.raises(ConfigurationError, match="could not"):
            resolve_app_environment({}, assume_hosted=True)

    def test_no_markers_and_explicit_development_is_refused(self) -> None:
        with pytest.raises(ConfigurationError, match="developer"):
            resolve_app_environment({"APP_ENV": "development"}, assume_hosted=True)

    def test_an_explicit_deployed_environment_is_accepted(self) -> None:
        resolved = resolve_app_environment({"APP_ENV": "production"}, assume_hosted=True)
        assert resolved is AppEnvironment.PRODUCTION

    def test_platform_metadata_is_still_used_when_present(self) -> None:
        resolved = resolve_app_environment(VERCEL_PREVIEW, assume_hosted=True)
        assert resolved is AppEnvironment.STAGING


class TestVercelDevCommand:
    """The vercel dev command reports development while running on a local machine."""

    def test_it_resolves_to_development(self) -> None:
        assert resolve_app_environment(VERCEL_DEV_COMMAND) is AppEnvironment.DEVELOPMENT

    def test_it_is_an_explicit_platform_statement_not_a_fallback(self) -> None:
        """Contrast with a missing VERCEL_ENV, which fails rather than defaulting."""
        assert resolve_app_environment(VERCEL_DEV_COMMAND) is AppEnvironment.DEVELOPMENT
        with pytest.raises(ConfigurationError):
            resolve_app_environment({"VERCEL": "1"})

    def test_an_explicit_app_env_still_wins(self) -> None:
        environ = VERCEL_DEV_COMMAND | {"APP_ENV": "test"}
        assert resolve_app_environment(environ) is AppEnvironment.TEST


class TestRequestHeadersCannotInfluenceTheEnvironment:
    """Only server-side variables are trusted.

    Resolution happens once at startup, before any request exists, so a header cannot
    reach it even in principle. These tests pin that a header-shaped variable, which
    is how a proxy would smuggle one into the environment, changes nothing.
    """

    HEADER_SHAPED: ClassVar[dict[str, str]] = {
        "HTTP_X_VERCEL_ENV": "development",
        "HTTP_X_FORWARDED_HOST": "localhost",
        "HTTP_HOST": "localhost",
        "X_VERCEL_ENV": "development",
        "HTTP_APP_ENV": "development",
    }

    def test_header_shaped_variables_do_not_downgrade_production(self) -> None:
        environ = VERCEL_PRODUCTION | self.HEADER_SHAPED
        assert resolve_app_environment(environ) is AppEnvironment.PRODUCTION

    def test_header_shaped_variables_do_not_downgrade_preview(self) -> None:
        environ = VERCEL_PREVIEW | self.HEADER_SHAPED
        assert resolve_app_environment(environ) is AppEnvironment.STAGING

    def test_header_shaped_variables_do_not_imply_hosting(self) -> None:
        assert detect_platform(self.HEADER_SHAPED) is HostingPlatform.LOCAL
