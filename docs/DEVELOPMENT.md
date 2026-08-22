# Development

Windows-native. Every command below is PowerShell, run from the repository root, and
none of them requires changing your execution policy: there are no `.ps1` wrappers by
design.

## Prerequisites

| Tool | Version used | Why |
|---|---|---|
| Python | 3.14.x | Pinned to `>=3.14,<3.15` in `pyproject.toml` |
| uv | 0.12+ | Dependency resolution, locking, and the virtual environment |
| Git for Windows | 2.x | Version control |
| Docker Desktop | 29.x | Development PostgreSQL only |

Node.js is not needed yet. There is no frontend build, because there is no
TypeScript to build.

## First-time setup

Install dependencies and create `.venv`:

```powershell
uv sync
```

Create your local environment file and edit it:

```powershell
Copy-Item .env.example .env
```

`.env` is git-ignored. Never commit it.

## Development database

Start PostgreSQL:

```powershell
docker compose -f infra/containers/docker-compose.yml up -d --wait
```

`--wait` blocks until the container reports healthy, so the next command does not
race against database initialisation.

Apply migrations:

```powershell
uv run alembic upgrade head
```

Stop it, keeping data:

```powershell
docker compose -f infra/containers/docker-compose.yml stop
```

Delete it, including the data volume:

```powershell
docker compose -f infra/containers/docker-compose.yml down -v
```

### Use 127.0.0.1, never localhost

The container publishes on IPv4 loopback only. On Windows, `localhost` resolves to
`::1` first, and connecting to a service that is not listening there stalls before
falling back to IPv4. Measured on this project: **130 seconds** per connection with
`localhost` against **0.6 seconds** with `127.0.0.1`.

If database work suddenly feels like it has hung, this is almost certainly why. Check
the host in `DATABASE_URL`.

## Running the application

```powershell
uv run flask --app learning_platform.web:create_app run --port 5000
```

Then check it is alive:

```powershell
curl.exe http://127.0.0.1:5000/healthz
```

Readiness, which also checks the database:

```powershell
curl.exe http://127.0.0.1:5000/readyz
```

The Flask development server is not a production runtime. Production is Vercel
(ADR 0002).

## Background work

Durable background work is a `task_dispatch` table drained on demand (ADR 0004).
There is no queue to run, no broker to install, and no worker process to keep alive.

Dispatch a no-op task that proves the whole path works:

```powershell
uv run flask --app learning_platform.web:create_app tasks verify --note local-check
```

Run whatever is currently due:

```powershell
uv run flask --app learning_platform.web:create_app tasks drain
```

Count tasks by state:

```powershell
uv run flask --app learning_platform.web:create_app tasks status
```

`drain` deliberately makes one pass rather than looping. In a deployment every drain
is a fresh invocation with a bounded budget, and a long-running local worker would
diverge from that in ways only discovered after deploying.

`status` reports counts per state. The one worth watching is `exhausted`: it counts
work the platform accepted and then failed to complete within its retry budget.

The same code runs behind `POST /internal/tasks/drain`, which is what a scheduled
invocation calls. That endpoint denies every request unless `TASK_RUNNER_SECRET` is
set, so it is inert locally by default and the commands above are the local path.

### Writing a handler

Handlers live in `src/learning_platform/worker/` and are registered explicitly in
`worker/registry.py`. A handler takes a `TaskContext` and does its work; it owns no
loop, no scheduler, and no transaction it did not open, and it imports `application`
and `domain` only.

Two obligations are not optional:

- **Be idempotent.** Delivery is at-least-once. A handler will eventually run twice
  for one dispatch, and `TaskContext.attempt` above 1 means a previous try did not
  finish.
- **Revalidate authorization.** A task may run long after the request that asked for
  it, by which time a grant may have been revoked. Raise `TaskFailed` with
  `TaskFailureKind.AUTHORIZATION_INVALIDATED` rather than proceeding.

Dispatch from a use case inside the transaction that justifies the work:

```python
with unit_of_work_factory() as unit_of_work:
    unit_of_work.resources.add(resource)
    unit_of_work.tasks.dispatch(
        INDEX_RESOURCE,
        {"resource_id": str(resource.id)},
        idempotency_key=f"index-{resource.id}-{resource.version}",
    )
```

Both writes commit together or neither does. That is the point: there is no state
where the resource exists but the indexing request was lost, and none where indexing
was requested for a resource that was rolled back.

## Tests

Everything:

```powershell
uv run pytest
```

Without the database-backed tests, which skip automatically when `DATABASE_URL` is
unset:

```powershell
uv run pytest -m "not integration"
```

One file:

```powershell
uv run pytest tests/web/test_app_factory.py
```

With coverage:

```powershell
uv run pytest --cov=learning_platform --cov-report=term-missing
```

Integration tests require PostgreSQL running and migrated. They skip rather than
fall back to SQLite: a SQLite substitute would silently stop exercising JSONB, UUID,
and timezone-aware timestamp behaviour, which is what those tests exist to check.

## Code quality

Lint:

```powershell
uv run ruff check .
```

Lint and fix what is safely fixable:

```powershell
uv run ruff check . --fix
```

Format:

```powershell
uv run ruff format .
```

Type check:

```powershell
uv run mypy
```

All three plus the tests, which is what to run before considering a change finished:

```powershell
uv run ruff format --check . ; uv run ruff check . ; uv run mypy ; uv run pytest
```

## Where configuration belongs

| Kind | Location | Committed |
|---|---|---|
| Secrets and connection strings | `.env`, or the hosting environment | Never |
| Variable names and safe defaults | `.env.example` | Yes |
| Deployment product data: institutions, branches, policies | `config/deployments/*.yaml` | Yes |
| Application behaviour and validation | `src/learning_platform/infrastructure/config/settings.py` | Yes |

Deployment values such as institution and branch names are configuration data. They
never become Python enums or branches in domain logic; the platform is
institution-neutral, and an architecture test enforces it.

Staging and production refuse to start without `SECRET_KEY`, `DATABASE_URL`,
`DEPLOYMENT_KEY`, and an https `APP_BASE_URL`. That failure is intentional.

`TASK_RUNNER_SECRET` is deliberately *not* required at startup. An unset value makes
the drain endpoint deny every request, so a deployment with no background work
configured serves ordinary traffic normally, and one with scheduled drains simply
does nothing until the secret is set. Failing to boot over it would be the wrong
trade: inert is safe, and a refused boot is not.

Generate a signing key:

```powershell
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
```

## Project layout

```text
src/learning_platform/
  domain/          framework-neutral entities, policies, value objects
  application/     use cases and ports (interfaces)
  infrastructure/  config, database, observability, audit, tasks
  web/             Flask composition, blueprints, error handling
  worker/          background task handlers and the task registry (ADR 0004)
frontend/shared/   design tokens
infra/
  containers/      development-only container definitions
  migrations/      Alembic revisions
tests/
  architecture/    dependency-direction enforcement
  integration/     PostgreSQL-backed
  security/        redaction and leakage
  unit/  web/
```

The importable package is `learning_platform`, not `platform`, which would shadow a
standard-library module. See ARCHITECTURE.md.

Dependencies point inwards: `web` → `application` → `domain`. `domain` imports no
framework, and nothing below `web` reads Flask request globals.
`tests/architecture/test_layer_boundaries.py` fails the build if that is violated.

## Deploying a preview to Vercel

Production hosting is Vercel (ADR 0002). Everything in this section was verified on a
real preview deployment; nothing here is inferred from documentation alone.

### How the application is exposed

`wsgi.py` at the repository root is the hosting adapter. It exposes `app`, which
Vercel's Python runtime loads as a WSGI application, and does nothing else:

```python
app = create_app(load_hosted_settings())
```

`load_hosted_settings` rather than the plain loader: importing this module proves a
platform imported it, which is a stronger fact than sniffing for Vercel environment
variables, all of which depend on a project setting that can be switched off.

`pyproject.toml` points at it explicitly:

```toml
[tool.vercel]
entrypoint = "wsgi:app"
```

Auto-detection by filename would also work, but is deliberately not relied upon: this
repository uses a `src` layout and Vercel also scans `src/` for entrypoint filenames.

No `vercel.json` and no `requirements.txt` exist. Vercel reads dependencies from
`uv.lock` and the Python version from `.python-version`, both of which are already
committed. Add configuration only when something concrete needs it.

### One-time project setup

```powershell
vercel link
```

### Required environment variables

Set these for the **Preview** environment before the first deployment. Without them
the function fails to boot, which is intended: a deployment that cannot be configured
safely must not serve requests.

| Variable | Purpose |
|---|---|
| `APP_ENV` | Optional on Vercel; derived from `VERCEL_ENV` when absent. Set it to `staging` or `production` to be explicit. It can never be `development` or `test` on a hosted deployment. |
| `SECRET_KEY` | Session signing. At least 32 characters. Generate a fresh one per environment. |
| `DATABASE_URL` | PostgreSQL URL. Required in deployed environments even before a database exists. |
| `DEPLOYMENT_KEY` | Which deployment configuration applies. |
| `APP_BASE_URL` | Externally visible https origin. |
| `DATABASE_CONNECT_TIMEOUT_SECONDS` | Optional. Lower than the default 10 keeps `/readyz` inside the function budget while no database is reachable. |
| `TASK_RUNNER_SECRET` | Optional. Authenticates the background drain endpoint. Unset means the endpoint denies everything, which is the correct inert state until scheduled work is wanted. Must equal `CRON_SECRET` when a cron job is configured. |

Generate a signing key without it appearing in your shell history or scrollback:

```powershell
python -c "import secrets; print(secrets.token_urlsafe(48), end='')" > key.txt; cmd /c "vercel env add SECRET_KEY preview --force < key.txt"
```

Delete `key.txt` afterwards. Never commit a secret, and never paste one into a
document, a test, or a commit message.

### A hosted deployment can never run as development

`APP_ENV` defaults to development, which is right locally and dangerous anywhere else.
When the process is hosted, the environment is resolved from Vercel's own
`VERCEL_ENV` instead: `production` becomes production, `preview` becomes staging.
`development` and `test` are refused outright on a hosted deployment, and a hosted
process whose environment cannot be identified refuses to start rather than
defaulting.

This exists because it was breached. Vercel assigns a new project's first deployment
to the production target regardless of flags, that deployment had no `APP_ENV`, and it
served a public URL in development mode with a `/readyz` that falsely reported ready.

The rule is in `src/learning_platform/infrastructure/config/hosting.py` and is
documented in ADR 0002. Only server-side environment variables are read, once, at
startup; request headers cannot influence it.

### Setting variables from PowerShell: use a file, not a pipe

Piping a string directly into `vercel env add` from PowerShell can prefix the value
with a UTF-8 byte-order mark. The BOM is invisible in the dashboard and breaks the
value silently. This was observed: `APP_ENV` arrived as `﻿staging` and was
rejected as an invalid environment name, and `DATABASE_CONNECT_TIMEOUT_SECONDS`
arrived as `﻿2` and failed to parse as an integer.

Write the value with an explicit BOM-free encoding and redirect it through `cmd`:

```powershell
[IO.File]::WriteAllText("value.txt", "staging", (New-Object System.Text.UTF8Encoding $false)); cmd /c "vercel env add APP_ENV preview --force < value.txt"
```

### Deploy and inspect

A preview deployment, never production:

```powershell
vercel deploy
```

The very first deployment of a brand-new project is assigned to the production target
by Vercel regardless of flags. Every later `vercel deploy` is a preview. `--prod` is
what promotes a deployment, and it is not used here.

Vercel Authentication protects preview deployments by default, so an ordinary request
is redirected to an SSO login. Test through the authenticated CLI rather than turning
protection off:

```powershell
vercel curl https://your-preview-url.vercel.app/healthz -- -s -D -
```

Runtime logs, including the structured JSON the application emits:

```powershell
vercel logs https://your-preview-url.vercel.app --json
```

### What the health endpoints mean on Vercel

- `/healthz` returns 200 whenever the function booted. It checks nothing external, so
  a database outage cannot turn into a restart loop. Verified returning 200 against a
  deployment with no reachable database.
- `/readyz` returns 503 with `{"checks": {"database": "unavailable"}}` when a database
  is configured but unreachable. This is the correct answer while no database has been
  provisioned, and it is deliberately not softened to make a preview look green.

### Deliberately unresolved

- No production deployment, deliberately. The project has no Production environment
  variables and its production URL answers `DEPLOYMENT_NOT_FOUND`. Only previews exist.
- No managed PostgreSQL. `DATABASE_URL` currently points at a host that cannot resolve,
  so readiness reports the truth. Provisioning is a separate task.
- Connection pooling strategy for a serverless runtime.
- `APP_BASE_URL` is a fixed project URL rather than the per-deployment preview URL.
- Static assets. Vercel serves `public/**` from its CDN and Flask's `static_folder`
  must not be used. No `public/` directory exists yet, so every path routes to the
  function; the design tokens in `frontend/shared/` are published with the first page
  that uses them.
- Attaching a scheduled drain. Vercel Cron invokes the **production** deployment URL
  only, and this project has no production deployment, so the trigger is unproven on
  Vercel even though the endpoint it would call is fully tested. Enabling it needs a
  production deployment, `TASK_RUNNER_SECRET` and `CRON_SECRET` set to the same value,
  and a `crons` entry in a `vercel.json` that does not yet exist. On the Hobby plan a
  cron may fire at most once per day, and a more frequent expression fails the
  deployment outright.

## Notes for PyCharm

- Set the interpreter to `.venv\Scripts\python.exe`.
- Mark `src` as Sources Root and `tests` as Test Sources Root.
- Marking `src` as a sources root is exactly the situation that would make a package
  named `platform` shadow the standard library. It is safe here because the package
  is named `learning_platform`.

## Outstanding operational work

Not blocking development, but required before a real deployment:

- Restrict `UPDATE` and `DELETE` on `audit_events` at the database-role level. The
  application never issues them, but the table is only append-oriented by convention
  until the grants enforce it.
- Configure the scheduled drain in a deployment: `TASK_RUNNER_SECRET`, a matching
  `CRON_SECRET`, and a `crons` entry. Until that exists, dispatched work accumulates
  in `task_dispatch` and is only executed by running the command by hand. Nothing is
  lost, but nothing runs on its own either.
- Decide the production connection-pooling strategy for a serverless runtime.
