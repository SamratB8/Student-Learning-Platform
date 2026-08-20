# Architecture

## Architectural style

Begin as a modular monolith with explicit domain boundaries, one relational database, protected object storage, and background workers. This keeps deployment and transactions manageable for a small team while preserving seams that can later become services if measured load or isolation needs justify it.

ADR 0001 selects a Flask/SQLAlchemy/PostgreSQL modular monolith with server-rendered ordinary surfaces, focused TypeScript browser applications for client-heavy areas such as Matrix, and a separate worker process. Domain language, interfaces, security constraints, and data ownership remain framework-independent.

## System context

```text
Browser / installable web experience
             |
             v
Custom platform UI + application API
             |
   +---------+----------+--------------+
   |                    |              |
PostgreSQL       Protected objects   Background jobs
   |                    |              |
   +------------- platform-owned state-+
             |
   +---------+-----------+-------------+---------------+
   |                     |             |               |
Google OAuth/Classroom  Calendar     Meet            Matrix
identity + source feed  sync         live calls      messaging/E2EE
             |
       one-way authenticated
       ChatGPT draft receiver
```

## Domain modules

- `identity`: Google identities, sessions, applications, approval lifecycle, devices.
- `tenancy`: deployments, institutions, programmes, branches, cohorts, terms, subjects.
- `authorization`: roles, capabilities, scope grants, policy evaluation.
- `academics`: resources, stored objects, provenance, canonical notes, contributions, review.
- `classroom`: connections, courses, shared mappings, ingestion records, four logical branch pools.
- `scheduling`: routines, notices, deadlines, events, Calendar sync, Meet links.
- `community`: platform groups, membership, moderation, Matrix mappings.
- `messaging`: Matrix client/session coordination only; no duplicate message store.
- `notifications`: in-app events, preferences, delivery state, required-integration reminders.
- `search`: permission-filtered academic/community index; no server plaintext index of E2EE messages.
- `administration`: approval queues, configuration, reports, system health.
- `audit`: append-oriented security and administrative events.
- `draft_ingress`: one-way ChatGPT draft validation and quarantine/review.
- `archive`: scoped exports, manifests, checksums, retention and transition workflows.

## Ownership boundaries

| Concern | Authoritative owner |
|---|---|
| Platform identity, approval, roles, branch, group membership | Platform database |
| Academic metadata, provenance, versions, publication | Platform database |
| Original Classroom item and assignment/submission truth | Google Classroom |
| Platform event/routine intent | Platform database |
| Synced calendar copy | Google Calendar |
| Live call media and admission | Google Meet |
| Message events, rooms, encrypted media | Matrix |
| Group purpose, visibility, moderators, allowed membership | Platform database |
| Draft publication decision | Platform admin workflow |

## Integration patterns

- Adapters isolate every provider from domain logic.
- Incoming provider events are idempotent and stored with provider ID, version/etag where available, received time, and processing result.
- Use an outbox for reliable platform-to-provider synchronization after database commits.
- Store refresh tokens and service credentials encrypted using deployment secret/key management, never in normal application tables or logs as plaintext.
- Retry transient failures with bounded backoff; send exhausted failures to an operator-visible dead-letter state.
- Reconciliation jobs repair missed notifications and drift.

## Classroom pools and deduplication

`ClassroomPool` is a logical authorization/catalogue boundary associated with a branch. A `ClassroomCourseMapping` connects one external course to a platform subject/scope. Many user connections may prove access to the same course, but ingestion produces one normalized external item per provider item ID. Imported files use content checksums so one immutable object can be referenced by several scoped resource records without widening permissions.

## Matrix integration

The web client uses a supported Matrix SDK behind a platform-owned messaging adapter and custom UI. Provisioning binds an approved platform account to a Matrix identity. Group creation binds one platform group to one Matrix room. Membership changes are coordinated and reconciled, with the platform policy remaining authoritative. Secrets that permit server administration are isolated from browser clients.

Message content is not copied into PostgreSQL for search, moderation convenience, or analytics. Reports contain only content deliberately submitted by a reporter and the minimum event reference necessary for review.

## Deployment model

- Separate development, test, staging, and production environments.
- PostgreSQL with migrations and point-in-time/verified backups.
- S3-compatible private object storage; downloads use short-lived authorization after policy evaluation.
- Queue/worker process for sync, indexing, scanning, notifications, and exports.
- Reverse proxy/edge with TLS, security headers, rate limiting, and request size limits.
- Central structured logs and metrics with privacy filtering.

## Proposed repository structure

```text
student-learning-platform/
  src/platform/
    web/                 # Flask composition, routes, forms, templates
    domain/              # framework-neutral entities and policies
    application/         # use cases, transactions, ports
    infrastructure/      # database, storage, queues, observability
    integrations/        # Google, Matrix provisioning, object storage
    worker/              # job entry point and handlers
  frontend/
    messaging/           # TypeScript custom Matrix client experience
    shared/              # project-owned browser utilities/design tokens
  config/
    deployments/cts.example.yaml
  docs/
  infra/
    containers/
    migrations/
    deployment/
  scripts/
  tests/
    architecture/
    security/
    integration/
```

Only documentation and safe configuration examples exist in Phase 0. Claude should create application folders as the first Phase 1 foundation task, following ADR 0001.

## Architecture decision gates

1. Verify maintained dependency releases and Matrix/Google SDK compatibility when creating Phase 1 lockfiles.
2. Record additional decisions as ADRs before foundational implementation.
3. Keep product policy out of provider adapters and CTS labels out of domain identifiers.
