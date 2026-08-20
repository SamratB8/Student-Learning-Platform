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

Current result: documentation/repository foundation, proprietary licensing, and stack ADR are complete. Phase 0 is ready for owner review and the first repository commit.

## Phase 1 - Core platform foundation

Environment/config validation, API/UI/worker skeletons, PostgreSQL migrations, base domain types, object storage abstraction, jobs/outbox, observability, audit framework, test harness, CI, and development/staging separation. Seed institution-neutral academic hierarchy plus CTS configuration.

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

## Phase 8 - Notifications, global search, and admin operations

Preference-aware notification center, permission-filtered global search, client-local encrypted message search, mobile admin portal, reports, integration health, and operational dashboards.

## Phase 9 - One-way ChatGPT draft receiver

Restricted credential, schemas, idempotency, quarantine/scanning, draft review UI, audit, and proof that read/publish/delete/admin paths are impossible for this principal.

## Phase 10 - Archive and BTech transition

Scoped export jobs, manifests/checksums, user contribution exports, retention/deletion runbooks, CTS freeze/revocation plan, and validated fresh BTech deployment configuration without automatic private-data carryover.

## Phase 11 - Hardening and launch

OAuth/authorization/upload/Matrix reviews, dependency and supply-chain review, penetration testing, accessibility, performance, disaster recovery, backup restores, incident runbooks, privacy/terms/ownership copy, and honest launch claims.
