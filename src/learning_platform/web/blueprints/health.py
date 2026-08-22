"""Liveness and readiness endpoints.

Two endpoints, because they answer different questions:

* ``/healthz`` asks whether this process is running. It checks nothing external, so a
  database outage cannot cause a restart loop.
* ``/readyz`` asks whether this process can currently serve traffic, which includes
  reaching the database.

Both are unauthenticated, so both are deliberately uninformative. They report status,
not versions, hostnames, dependency detail, or configuration.
"""

from __future__ import annotations

from typing import Any

from flask import Blueprint, jsonify
from flask.wrappers import Response

from learning_platform.infrastructure.database.engine import check_connection
from learning_platform.web.extensions import get_extensions

__all__ = ["health_blueprint"]

health_blueprint = Blueprint("health", __name__)


@health_blueprint.get("/healthz")
def liveness() -> tuple[Response, int]:
    """Report that the process is up."""
    return jsonify({"status": "ok"}), 200


@health_blueprint.get("/readyz")
def readiness() -> tuple[Response, int]:
    """Report whether dependencies needed to serve traffic are reachable.

    Answers 503 when a configured dependency is unreachable, so a load balancer stops
    sending traffic here. A database that is simply not configured, which is a valid
    state for early phases and for some tests, is reported as ``not_configured``
    rather than as a failure.
    """
    extensions = get_extensions()
    checks: dict[str, str] = {}
    ready = True

    if extensions.database_available:
        database_ok = check_connection(extensions.engine)
        checks["database"] = "ok" if database_ok else "unavailable"
        ready = ready and database_ok
    else:
        checks["database"] = "not_configured"

    body: dict[str, Any] = {"status": "ready" if ready else "not_ready", "checks": checks}
    return jsonify(body), 200 if ready else 503
