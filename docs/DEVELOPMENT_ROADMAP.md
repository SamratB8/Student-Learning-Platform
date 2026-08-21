# Development Roadmap

## Working rules

- Build in dependency order and keep each phase releasable behind feature flags where useful.
- Security, authorization, tests, migration safety, accessibility, and documentation are continuous work, not a final cleanup phase.
- Do not start a phase until its prerequisite decision/gate is satisfied.
- CTS-specific values come from deployment configuration.

## Phase 0 - Foundation (current)

Deliverables:

- Independent repository and non-secret configuration conventions.
- Frozen v1 product, architecture, security, data, permissions, integrations, and roadmap documents.
- Stack and repository ADR.
- No product feature implementation.

Exit gate:

- Stack ADR accepted, baseline documents consistent, proprietary licence present, and Phase 1 backlog created.

Current result: documentation/repository foundation, proprietary licensing, and stack ADR are complete. Phase 0 is committed.

## Phase 1 - Core platform foundation

Environment/config validation, application/UI/background skeletons, PostgreSQL migrations, base domain types, object storage abstraction, jobs/outbox, observability, audit framework, test harness, CI, and development/staging separation. Seed institution-neutral academic hierarchy plus CTS configuration.

### Phase 1A - Runnable foundation (complete)

Baseline documentation reconciliation for the post-Phase-0 approved decisions, the uv-managed Python 3.14 project, the `learning_platform` package with enforced layer boundaries, the Flask application factory, validated configuration, structured logging with redaction, the audit seam and its first migration, the SQLAlchemy and Alembic foundation, development PostgreSQL in Docker, design tokens, and the test and lint baseline.

No product features. Deliberately excluded: OAuth, RBAC behavior, Classroom, resources, notes, calendar, Matrix, search, AI, service worker, and device benchmarking.

### Phase 1B - Remaining foundation

Object storage adapter, the outbox, the durable task dispatch record, CI, staging separation, the academic hierarchy seed, and the CTS deployment configuration loader. ADR 0004 must be decided before any job that cannot complete inside one request.

## Phase 2 - Google identity and manual approval

Google OAuth, session lifecycle, application profile, manual approval states, account administration, re-authentication, audit, and negative authorization tests. No passwords or OTP systems.

## Phase 3 - RBAC and scoped permissions

Capabilities, roles, scoped grants, branch/subject/group policy evaluation, admin delegation UI, and exhaustive denial tests.

## Phase 4 - Classroom connection and academic resource engine

Required-connection reminders, four branch pools, course mapping, idempotent synchronization, linked/imported items, object scanning/deduplication, protected view/download, provenance badges, resource versioning, assignments/notices/deadlines projection, and search indexing.

## Phase 5 - Canonical notes and contributions

Three canonical note categories, source eligibility validation, version/review/publication workflow, student contributions, comparisons, and human-controlled merge proposals.

## Phase 6 - Public information, routine, and scheduling

Public/member publishing, structured routine, notices, unified events/deadlines, custom calendar, Google Calendar sync, and Google Meet link workflow.

## Phase 7 - Groups and Matrix messaging

Platform group lifecycle/membership, Matrix provisioning/mappings/reconciliation, custom conversations UI, DMs/groups, replies/reactions/receipts, files/images/voice/video notes, privacy-safe notifications, device verification/recovery design, and E2EE security gate. Meet remains the live-call path.

## Phase 8 - Notifications, global search, admin operations, and personal study surfaces

Preference-aware notification center with granular category and channel preferences, granular calendar subscription preferences, permission-filtered global search, client-local encrypted message search, mobile admin portal, reports, integration health, and operational dashboards.

Personal study surfaces belong here: bookmarks, recently viewed, collections, progress checklists, study tasks, resource reports, onboarding state, and individual user data export.

## Phase 8A - Devices and capability profiles

Device installation records with random revocable identifiers, consented capability measurement, and versioned profiles. Prerequisite for offering any on-device AI.

## Phase 8B - Student AI surfaces

Continue in ChatGPT deterministic context assembly and handoff, the internal AI utility port and its first adapter, and optional on-device Quick AI gated by capability profiles. ADR 0003 governs. Every path ships with a tested deterministic fallback.

## Phase 9 - One-way ChatGPT draft receiver

Restricted credential, schemas, idempotency, quarantine/scanning, draft review UI, audit, and proof that read/publish/delete/admin paths are impossible for this principal.

## Phase 10 - Archive and BTech transition

Scoped export jobs, manifests/checksums, user contribution exports, retention/deletion runbooks, CTS freeze/revocation plan, and validated fresh BTech deployment configuration without automatic private-data carryover.

## Phase 11 - Hardening and launch

OAuth/authorization/upload/Matrix/AI-boundary reviews, dependency and supply-chain review, penetration testing, accessibility audit, responsive verification across phone/tablet/desktop, PWA installability, performance, disaster recovery, backup restores, incident runbooks, privacy/terms/ownership copy, and honest launch claims.

## Continuous obligations

Responsive layout, keyboard access, focus visibility, contrast, reduced motion, and light/dark appearance are verified as each surface is built. They are not a Phase 11 cleanup.
