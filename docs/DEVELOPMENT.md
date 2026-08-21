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
  worker/          background handlers (no runtime chosen yet, ADR 0004)
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
- Choose the background execution runtime (ADR 0004). Until then, no feature may
  depend on work that cannot finish inside a single request.
- Decide the production connection-pooling strategy for a serverless runtime.
