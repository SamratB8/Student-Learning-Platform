# Student Learning Platform

An independently owned, institution-neutral student platform. The first deployment is configured for CTS, but CTS is not the owner, sponsor, or operator of the software.

## Start here

1. Read [PRODUCT_REQUIREMENTS.md](docs/PRODUCT_REQUIREMENTS.md).
2. Read [ARCHITECTURE.md](docs/ARCHITECTURE.md) and [SECURITY_MODEL.md](docs/SECURITY_MODEL.md).
3. Follow [DEVELOPMENT_ROADMAP.md](docs/DEVELOPMENT_ROADMAP.md) phase gates.
4. To run the code, read [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Current status

- Phase: 1A complete — a runnable, tested core foundation
- Product features: not implemented
- First deployment: CTS (`config/deployments/cts.example.yaml`)

Phase 1A delivers the application skeleton only: a Flask application factory,
validated configuration, enforced layer boundaries, structured logging with
redaction, the audit foundation and its first migration, PostgreSQL and Alembic, a
development database, design tokens, and the test and lint baseline.

Deliberately not implemented: Google OAuth, registration and approval, RBAC
behaviour, Classroom, the resource library, canonical notes, calendar and Meet,
Matrix, groups, search, AI, the service worker, and device benchmarking. Each belongs
to a later phase.

## Quick start

```powershell
uv sync
```

```powershell
Copy-Item .env.example .env
```

```powershell
docker compose -f infra/containers/docker-compose.yml up -d --wait
```

```powershell
uv run alembic upgrade head
```

```powershell
uv run flask --app learning_platform.web:create_app run --port 5000
```

```powershell
uv run pytest
```

Full instructions, including the code-quality commands and a Windows networking
caveat that matters, are in [DEVELOPMENT.md](docs/DEVELOPMENT.md).

## Stack

Python 3.14, Flask, SQLAlchemy 2.x, Alembic, PostgreSQL, pydantic-settings,
structlog, pytest, Ruff, and mypy. Dependencies are managed and locked by uv.

Server-rendered Jinja for ordinary surfaces; focused TypeScript browser applications
only where client complexity warrants it, chiefly the custom Matrix messaging
experience. No SPA framework. See [ADR 0001](docs/adr/0001-implementation-stack.md).

Production web hosting is Vercel. See [ADR 0002](docs/adr/0002-deployment-model.md).

The importable Python package is `learning_platform`. It is deliberately not named
`platform`, which would shadow a standard-library module.

## Architecture decisions

| ADR | Title | Status |
|---|---|---|
| [0001](docs/adr/0001-implementation-stack.md) | Implementation stack | Accepted |
| [0002](docs/adr/0002-deployment-model.md) | Deployment model and production hosting | Accepted |
| [0003](docs/adr/0003-student-ai-architecture.md) | Student AI architecture | Accepted |
| [0004](docs/adr/0004-background-execution.md) | Background execution runtime | Accepted |

## Licence

This is proprietary software. No use, copying, modification, distribution,
hosting, or derivative work is permitted without explicit written and signed
permission from the copyright owner. See [LICENSE](LICENSE).

## Ownership notice

This platform is privately owned and independently operated by its creator. It is not an official CTS website or service, and CTS does not own, sponsor, endorse, or administer it.
