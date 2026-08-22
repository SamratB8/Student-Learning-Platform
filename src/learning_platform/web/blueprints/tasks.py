"""The background drain endpoint.

ADR 0004 selected a durable table drained by a scheduled invocation, which means one
HTTP route exists whose purpose is to run background work. That route is the only
externally reachable part of the whole design, so it is worth being explicit about
what it does and does not accept.

**It takes no input.** Not a task type, not a payload, not a batch size, not an
identifier. It reads exactly one thing from the request: the ``Authorization`` header.
Everything about what runs comes from the database and from validated settings.

That is a structural property, not a validation rule. "Make the caller run an
arbitrary task" is not a request this endpoint can express, so it does not need to be
defended against, and no future change to payload parsing can reintroduce it. The
registry provides the second layer: even a task type written directly into the
database can only name a handler this deployment registered in Python.

Authentication is a shared secret compared in constant time. When no secret is
configured the endpoint denies everything, and it denies identically whether the
secret was wrong or absent, so probing it reveals nothing about how the deployment is
configured.
"""

from __future__ import annotations

import secrets

from flask import Blueprint, jsonify, request
from flask.wrappers import Response

from learning_platform.web.extensions import get_extensions

__all__ = ["tasks_blueprint"]

tasks_blueprint = Blueprint("tasks", __name__)

_BEARER_PREFIX = "Bearer "


@tasks_blueprint.route("/internal/tasks/drain", methods=["GET", "POST"])
def drain() -> tuple[Response, int]:
    """Run background work that is due.

    GET is accepted because the scheduler this design targets issues one: Vercel Cron
    makes an HTTP GET to the configured path. A mutating GET is normally worth
    refusing, and the usual reason to refuse it does not apply here, because nothing
    about this route is reachable by a browser acting on a user's behalf: it is not
    authenticated by cookie, and a cross-origin request cannot set an ``Authorization``
    header without a preflight this endpoint never answers.

    Returns 200 with counts, 401 when unauthenticated, or 503 when there is no
    database to drain.
    """
    extensions = get_extensions()

    if not _is_authorized(extensions.settings.task_runner_secret.get_secret_value()):
        # Deliberately uninformative, and identical for a wrong secret and an
        # unconfigured deployment. Whether background processing is switched on is
        # not something an unauthenticated caller gets to learn.
        return jsonify({"status": "denied"}), 401

    if not extensions.database_available:
        return jsonify({"status": "unavailable"}), 503

    report = extensions.task_runner.drain()

    # Counts only. Never task identifiers or types: whatever triggered this drain is
    # a scheduler, and it has no business learning what work the platform is doing.
    return (
        jsonify(
            {
                "status": "ok",
                "claimed": report.claimed,
                "succeeded": report.succeeded,
                "retried": report.retried,
                "exhausted": report.exhausted,
                "failed": report.failed,
            }
        ),
        200,
    )


def _is_authorized(expected: str) -> bool:
    """Compare the presented bearer token with the configured secret.

    An unconfigured secret denies rather than permits. That is the fail-closed
    direction, and it is the reason the secret is not required at startup: a
    deployment with no background work configured serves ordinary traffic normally,
    and one with scheduled drains simply does no work until the secret is set.
    """
    expected = expected.strip()
    if not expected:
        return False

    header = request.headers.get("Authorization", "")
    if not header.startswith(_BEARER_PREFIX):
        return False

    presented = header.removeprefix(_BEARER_PREFIX).strip()
    # Constant time, so the endpoint does not leak the secret one character at a
    # time to a caller willing to measure.
    return secrets.compare_digest(presented, expected)
