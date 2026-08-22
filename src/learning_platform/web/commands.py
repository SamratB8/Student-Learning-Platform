"""Command-line entry points for background work.

Local development needs a way to run due tasks without a scheduler, without a hosted
queue, and without paying for anything. These commands are that way, and they are the
same code path the deployed drain endpoint uses, so what a developer exercises
locally is what runs in a deployment.

They are administrative commands, run from a terminal by someone who already has the
database credentials. They perform no authentication of their own, and they must
never be exposed over HTTP: the drain endpoint exists for that and authenticates.
"""

from __future__ import annotations

import click
from flask import Flask
from flask.cli import AppGroup, with_appcontext

from learning_platform.infrastructure.tasks.repository import SqlAlchemyTaskDispatchStore
from learning_platform.web.extensions import get_extensions
from learning_platform.worker.maintenance import VERIFY_DISPATCH

__all__ = ["register_task_commands"]


def register_task_commands(app: Flask) -> None:
    """Attach the ``tasks`` command group to ``app``."""
    tasks = AppGroup("tasks", help="Inspect and run durable background work (ADR 0004).")

    tasks.command("drain", help="Run background work that is currently due.")(drain_command)
    tasks.command("status", help="Count dispatched tasks by state.")(status_command)
    tasks.command("verify", help="Dispatch a no-op task that proves the pipeline works.")(
        verify_command
    )

    app.cli.add_command(tasks)


@with_appcontext
def drain_command() -> None:
    """Claim and run due tasks once, then report what happened.

    Deliberately one pass rather than a loop. A long-running local worker would
    diverge from the deployed behaviour, where every drain is a fresh invocation with
    a bounded budget, and the differences would only be discovered in a deployment.
    Run it again, or from a scheduled task, if you want repetition.
    """
    report = get_extensions().task_runner.drain()
    click.echo(
        f"claimed={report.claimed} succeeded={report.succeeded} "
        f"retried={report.retried} exhausted={report.exhausted} failed={report.failed}"
    )


@with_appcontext
def status_command() -> None:
    """Show how many tasks sit in each state.

    ``exhausted`` is the number worth watching: it counts work the platform accepted
    and then failed to complete within its retry budget.
    """
    extensions = get_extensions()
    with extensions.unit_of_work() as unit_of_work:
        # The concrete store, not the port. Counting queue depth is a diagnostic, and
        # putting it on the port would invite a use case to branch on it.
        counts = SqlAlchemyTaskDispatchStore(unit_of_work.session).count_by_state()

    if not counts:
        click.echo("no dispatched tasks")
        return
    for state, total in sorted(counts.items()):
        click.echo(f"{state}: {total}")


@click.option("--note", default=None, help="An optional marker echoed in the task payload.")
@with_appcontext
def verify_command(note: str | None) -> None:
    """Dispatch ``maintenance.verify_dispatch``.

    Proves the durable path end to end without touching product data: this commits a
    row, and a later drain runs it. Useful immediately after configuring a scheduled
    drain in a new environment.
    """
    extensions = get_extensions()
    payload = {"note": note} if note is not None else {}

    with extensions.unit_of_work() as unit_of_work:
        receipt = unit_of_work.tasks.dispatch(VERIFY_DISPATCH, payload)

    click.echo(f"dispatched {receipt.task_id}")
    click.echo("run 'flask tasks drain' to execute it")
