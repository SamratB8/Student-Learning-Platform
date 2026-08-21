"""Typed, validated deployment configuration."""

from learning_platform.infrastructure.config.environments import AppEnvironment
from learning_platform.infrastructure.config.hosting import (
    HostingPlatform,
    detect_platform,
    resolve_app_environment,
)
from learning_platform.infrastructure.config.settings import (
    Settings,
    load_hosted_settings,
    load_settings,
)

__all__ = [
    "AppEnvironment",
    "HostingPlatform",
    "Settings",
    "detect_platform",
    "load_hosted_settings",
    "load_settings",
    "resolve_app_environment",
]
