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
- `personal`: per-user bookmarks, recently viewed items, progress checklists, study tasks, and collections.
- `devices`: installation records and versioned capability profiles used to decide whether optional on-device work is viable.
- `assistance`: authorization-first context assembly for the ChatGPT handoff, and the internal AI utility port. It never bypasses `authorization`.

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

## AI architecture

ADR 0003 is authoritative. Structurally there are three separate things, and they must not be merged into one "AI service":

- Quick AI executes in the browser on the user's device where the capability profile permits. It is optional and the platform never depends on it.
- Continue in ChatGPT is a deterministic export path. Authorization runs first, retrieval returns only permitted academic context, ordinary code assembles a source-marked prompt, and the user carries it to their own ChatGPT account by clipboard. The platform never calls, automates, or authenticates against ChatGPT.
- The internal AI utility is a server-side port with a single initial adapter. It is not reachable from any student-facing route.

The internal AI utility complements deterministic code, retrieval, and indexing. It never replaces them. The order of preference is deterministic code and rules, then retrieval and indexing, then optional AI enhancement. When the provider fails, is disabled, is rate limited, or is removed entirely, retrieval, prompt preparation, and the academic library continue working with reduced polish and no loss of correctness. Never use a model where ordinary code is reliable, cheap, and deterministic.

Authorization happens before retrieval, and retrieval happens before anything is sent to an external provider. The privacy boundary is defined in SECURITY_MODEL.md.

## Device capability profiles

`DeviceInstallation` records a randomly generated installation identifier chosen by the client and stored against the user. It is not a hardware fingerprint and must not be reconstructed from hardware attributes. Each installation may have several `CapabilityProfile` versions, because measurements are invalidated by hardware, browser, and benchmark changes.

Profiles record measured behavior rather than reported hardware names, since browsers do not reliably expose CPU model, exact memory, GPU, or NPU details. Candidate measurements include computation throughput, WebGPU availability and performance, practical memory headroom, storage quota, network latency and throughput, and local model load and inference timing. Any measurement heavy enough to be noticeable requires consent and must not run on every visit.

Consumers ask the profile a capability question, such as whether on-device summarization is viable. They do not read raw benchmark numbers scattered through the codebase.

## Presentation architecture

Ordinary public, member, and admin surfaces are server-rendered Jinja. Client-heavy areas, chiefly the custom Matrix experience, are focused TypeScript browser applications. No single-page-application framework is adopted without an ADR that supersedes ADR 0001.

The design system is a project-owned token layer expressed as CSS custom properties. Tokens define colour roles, spacing, typography scale, radii, elevation, and motion. Appearance is selected as System, Light, or Dark; System follows `prefers-color-scheme` and an explicit choice overrides it. Because colours are referenced only through role tokens, dark mode is a token swap rather than a later retrofit.

Layout is responsive from content-driven breakpoints, not device names, and is exercised from roughly 320px upward. Interaction assumes touch first: pointer hover is an enhancement, focus states are always visible, and motion respects `prefers-reduced-motion`.

The application is designed to be installable (PWA-ready). Service worker and offline behavior are deliberately out of scope for early phases; the architecture only guarantees that adding them later does not require restructuring.

## Deployment model

Production hosting for the web application is Vercel. ADR 0002 records that decision and its consequences. The important architectural constraints are:

- Web request handling is a serverless invocation, not a long-lived process. Nothing may rely on in-process state surviving between requests, on background threads outliving a response, or on process-local caches, schedulers, or locks.
- The runtime filesystem is ephemeral and must be treated as read-only working space. Uploads, exports, and generated artefacts belong in object storage.
- PostgreSQL is an external managed service. Connection handling must tolerate many short-lived invocations; connection pooling strategy is a deployment concern, not an application assumption.
- Object storage is external, private, and S3-compatible. Downloads use short-lived authorization issued after a fresh policy evaluation.
- Matrix runs as a separate deployment and is never colocated with the web application.
- Background work cannot assume a colocated always-running worker. The application depends on a task-dispatch port; the concrete runtime is deferred to ADR 0004.
- TLS, security headers, rate limiting, and request size limits are enforced at the platform edge and in application configuration rather than by a self-managed reverse proxy.
- Separate development, test, staging, and production environments, each with its own database, bucket/prefix, and credentials.
- PostgreSQL migrations with point-in-time or otherwise verified backups.
- Central structured logs and metrics with privacy filtering.

Local development is Windows-native. Development PostgreSQL runs in Docker Desktop. The development server is not a production runtime.

## Internal Python package name

The product and repository are named "Student Learning Platform". The importable Python package is `learning_platform`, distributed as `student-learning-platform`.

`platform` was rejected as an import name because it shadows the `platform` standard-library module. This was verified rather than assumed: with a `src` directory at the front of `sys.path`, which is the normal result of marking `src` as a sources root in an IDE or of test-runner path insertion, `import platform` resolves to the project package instead of the standard library. Alembic, SQLAlchemy, and packaging tooling all import `platform`, so the failure mode is a confusing breakage in dependencies rather than in project code.

## Repository structure

```text
student-learning-platform/
  src/learning_platform/
    domain/              # framework-neutral entities, policies, value objects
    application/         # use cases and ports (interfaces) only
    infrastructure/      # config, database, observability, audit, tasks
    integrations/        # Google, Matrix provisioning, object storage adapters
    web/                 # Flask composition, blueprints, templates, error handling
    worker/              # background job handlers, invoked by the chosen runtime
  frontend/
    shared/              # project-owned design tokens and browser utilities
    messaging/           # TypeScript custom Matrix client experience
  config/
    deployments/cts.example.yaml
  docs/
    adr/
  infra/
    containers/          # development-only container definitions
    migrations/          # Alembic revision history
  tests/
    architecture/        # dependency-direction and boundary enforcement
    integration/         # PostgreSQL-backed tests
    security/            # denial and leakage tests
    unit/
    web/
  scripts/
```

Directories are created when they have a near-term purpose, not in advance.

## Dependency direction

```text
web  ->  application  ->  domain
worker  ->  application  ->  domain
infrastructure  ->  application  ->  domain
integrations  ->  application  ->  domain
```

- `domain` imports nothing from Flask, SQLAlchemy, Alembic, pydantic-settings, or any provider SDK.
- `application` defines ports and orchestrates use cases. It imports `domain` only.
- `infrastructure` and `integrations` implement ports. They may import frameworks and provider SDKs.
- `web` composes: it wires configuration and adapters into the application layer and handles HTTP concerns.
- No layer below `web` reads Flask request globals. Request-scoped values are passed explicitly or carried in a framework-neutral context variable.

This direction is enforced by an automated test, not by convention alone.

## Architecture decision gates

1. Verify maintained dependency releases and Matrix/Google SDK compatibility when creating Phase 1 lockfiles.
2. Record additional decisions as ADRs before foundational implementation.
3. Keep product policy out of provider adapters and CTS labels out of domain identifiers.
4. Select the background execution runtime through ADR 0004 before implementing any job that cannot complete inside a single request.
5. Confirm any code that would run on Vercel does not depend on process lifetime, local filesystem persistence, or in-process scheduling.
