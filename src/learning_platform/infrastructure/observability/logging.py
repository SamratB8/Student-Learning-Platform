"""Structured logging with mandatory redaction.

Console rendering in development, one JSON object per line when deployed. Every
record carries the current correlation identifier so a request can be reconstructed
from aggregated logs.

Redaction runs as a processor rather than at call sites. Relying on every future call
site to remember the rule would guarantee an eventual leak, whereas a processor
applies it to everything.

Standard-library logging, which is what Flask, Werkzeug, SQLAlchemy, and Alembic use,
is routed through the same processor chain via ``ProcessorFormatter``. Without that,
library output would bypass redaction entirely, so this is a security property rather
than a formatting preference.

These are operational logs. They are not the audit trail; see
``learning_platform.domain.audit``.
"""

from __future__ import annotations

import logging
import sys
from typing import Any

import structlog
from structlog.typing import EventDict, FilteringBoundLogger, Processor, WrappedLogger

from learning_platform.domain.sensitive import REDACTED, is_sensitive_key
from learning_platform.infrastructure.config.settings import LogFormat, Settings
from learning_platform.infrastructure.observability.context import current_correlation_id

__all__ = ["configure_logging", "get_logger"]

_MAX_NESTING_DEPTH = 6


def _redact_value(value: Any, depth: int = 0) -> Any:
    """Recursively redact sensitive keys inside a log value.

    Depth is bounded so a deeply nested structure cannot turn a log call into an
    expensive traversal.
    """
    if depth >= _MAX_NESTING_DEPTH:
        return value
    if isinstance(value, dict):
        return {
            key: REDACTED if is_sensitive_key(str(key)) else _redact_value(item, depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, list | tuple):
        redacted = [_redact_value(item, depth + 1) for item in value]
        return tuple(redacted) if isinstance(value, tuple) else redacted
    return value


def _redact_processor(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Replace values whose field name indicates a secret."""
    for key in list(event_dict):
        if key == "event":
            # The message itself is free text and cannot be inspected reliably.
            # Callers put data in structured fields, not in the message.
            continue
        if is_sensitive_key(str(key)):
            event_dict[key] = REDACTED
        else:
            event_dict[key] = _redact_value(event_dict[key])
    return event_dict


def _correlation_processor(_logger: WrappedLogger, _name: str, event_dict: EventDict) -> EventDict:
    """Attach the current correlation identifier, when one is bound."""
    correlation_id = current_correlation_id()
    if correlation_id is not None:
        event_dict.setdefault("correlation_id", correlation_id)
    return event_dict


def _shared_processors() -> list[Processor]:
    """Processors applied to project and library records alike.

    Redaction is last, so it also covers fields added by the processors before it.
    """
    return [
        structlog.contextvars.merge_contextvars,
        structlog.stdlib.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        _correlation_processor,
        _redact_processor,
    ]


def configure_logging(settings: Settings) -> None:
    """Configure structlog and the standard library root logger.

    Safe to call more than once; the last call wins. The application factory calls it
    during startup, and tests call it per configuration.
    """
    level = getattr(logging, settings.log_level, logging.INFO)
    shared = _shared_processors()

    renderer: Processor
    if settings.effective_log_format is LogFormat.JSON:
        # Tracebacks become structured data rather than a raw text blob, so an
        # aggregator can index them and a formatted value cannot smuggle a secret
        # past redaction inside a message string.
        shared.append(structlog.processors.dict_tracebacks)
        renderer = structlog.processors.JSONRenderer()
    else:
        renderer = structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())

    structlog.configure(
        processors=[*shared, structlog.stdlib.ProcessorFormatter.wrap_for_formatter],
        logger_factory=structlog.stdlib.LoggerFactory(),
        wrapper_class=structlog.make_filtering_bound_logger(level),
        cache_logger_on_first_use=False,
    )

    formatter = structlog.stdlib.ProcessorFormatter(
        # Applied to records that came from the standard library rather than from
        # structlog, which is how library logs reach the redaction processor.
        foreign_pre_chain=shared,
        processors=[
            structlog.stdlib.ProcessorFormatter.remove_processors_meta,
            renderer,
        ],
    )

    handler = logging.StreamHandler(stream=sys.stderr)
    handler.setFormatter(formatter)

    root = logging.getLogger()
    for existing in root.handlers[:]:
        root.removeHandler(existing)
    root.addHandler(handler)
    root.setLevel(level)

    # Werkzeug's per-request access log duplicates what the request middleware
    # records and is noisy in development.
    logging.getLogger("werkzeug").setLevel(max(level, logging.WARNING))


def get_logger(name: str) -> FilteringBoundLogger:
    """Return a bound logger for a module."""
    logger: FilteringBoundLogger = structlog.get_logger(name)
    return logger
