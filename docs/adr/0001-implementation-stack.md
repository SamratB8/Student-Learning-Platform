# ADR 0001: Implementation Stack

- Status: Accepted for Phase 1
- Date: 20 August 2026
- Decision basis: frozen v1 requirements and delivery constraints

## Context

The owner will use Claude to implement the platform. The product needs a secure modular backend, server-rendered public/admin/member surfaces that are fast to build, background integration work, PostgreSQL, and a rich custom Matrix messaging experience.

## Decision

Build a clean, independent modular monolith using:

- Python and Flask for the application/API composition root and server-rendered public, member, and admin surfaces.
- SQLAlchemy and Alembic against PostgreSQL for persistence and migrations.
- Jinja plus a project-owned responsive design system for ordinary pages.
- TypeScript bundled as focused browser applications where client complexity warrants it, especially the custom Matrix UI using the supported Matrix JavaScript SDK.
- A separate worker process sharing domain/application packages for Classroom/Calendar synchronization, indexing, scanning, notifications, outbox delivery, and archives. Select the concrete queue/runtime in a later ADR after deployment constraints are known.
- S3-compatible private object storage through a provider-neutral adapter.
- Pytest plus browser-level and security-denial testing. PostgreSQL-backed integration tests are required; SQLite may be used only for tests that do not depend on database-specific behavior.

Dependency versions will be selected and locked during Phase 1 after checking maintained supported releases and compatibility.

## Consequences

- Claude can work in a familiar Python architecture while the Matrix client remains capable and maintainable in TypeScript.
- Public/admin pages avoid the complexity of making the entire product a single-page application.
- Domain policies and provider adapters must not depend on Flask request globals, keeping worker and test use practical.
- Transaction commits belong to application use cases, not model `save()` helpers.
- All implementation and project assets remain governed by the repository's proprietary licence and applicable third-party terms.

## Rejected alternatives

- Entire product as a frontend SPA plus separate API: rejected for Phase 1 because it adds delivery and authorization surface without enough benefit for mostly content/admin workflows.
- Server-render every messaging interaction: rejected because Matrix synchronization, encryption/device state, recording, reactions, and local search require substantial client-side behavior.
