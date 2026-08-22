# ADR 0004: Background Execution Runtime

- Status: Open. Constraints accepted; runtime not selected.
- Date: 21 August 2026
- Blocks: Classroom synchronization, search indexing, malware scanning, notification fan-out, outbox delivery, archive generation

## Context

ADR 0001 assumed "a separate worker process". ADR 0002 makes Vercel the production web target, so a colocated always-running worker is not available. A runtime must eventually be chosen, but choosing one now would be guessing before the workloads are understood.

Phase 1A therefore records the constraints and creates the seam, and defers the choice.

## Accepted constraints

1. Application code dispatches work through a port. It never imports a queue client, a broker SDK, or a scheduler directly.
2. A dispatched task is described by a stable name and a JSON-serializable payload containing internal IDs, never entity graphs, secrets, tokens, or message plaintext.
3. Tasks are idempotent. Any runtime worth selecting will retry, and serverless platforms may invoke twice.
4. Tasks are enqueued only after the database transaction that justifies them commits. Reliable provider-facing work uses the outbox pattern described in ARCHITECTURE.md.
5. A task must not assume it runs in the same process, host, or region as the request that dispatched it.
6. No always-running worker is assumed, and none is added casually.
7. Failure is visible. Exhausted retries reach an operator-visible dead-letter state rather than disappearing.

## Phase 1A implementation

An inline dispatcher that runs the handler synchronously inside the caller. This is correct for development and tests, honest about what it does, and deliberately unsuitable for production workloads. It exists so the port has an implementation and so the seam is exercised, not because inline execution is the plan.

The port must never be used in production with the inline implementation for work that can exceed a request timeout.

## Options to evaluate when the decision is taken

- Vercel-native scheduled invocations plus a durable queue table in PostgreSQL, drained by scheduled runs.
- An external managed queue with HTTP delivery back into the application.
- A small externally hosted worker process sharing the domain and application packages, which is what ADR 0001 originally imagined, deployed outside Vercel.
- A managed workflow service for long-running multi-step jobs such as archive generation.

## Decision criteria

- Longest realistic task duration versus the platform invocation limit.
- Delivery guarantees and retry semantics.
- Whether it introduces a new paid service, and whether that cost is justified.
- Operational burden for a single maintainer.
- Whether failures are observable without building a monitoring stack.

## Consequences of leaving this open

No feature that requires work exceeding a single request may be implemented until this ADR is decided. That is an accepted, explicit blocker rather than an oversight.
