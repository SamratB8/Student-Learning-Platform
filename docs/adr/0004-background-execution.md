# ADR 0004: Background Execution Runtime

- Status: Accepted
- Date: 23 August 2026
- Supersedes: the "Open" state recorded in Phase 1A, and the inline dispatcher described there as a placeholder
- Unblocks: Classroom synchronization, search indexing, malware scanning, notification fan-out, Calendar sync, archive generation, internal AI preprocessing

## Context

ADR 0001 assumed "a separate worker process". ADR 0002 made Vercel the production web target, which removes the colocated always-running worker and with it the assumption that anything can outlive a request. Phase 1A recorded the constraints, created the port, and deferred the runtime because the workloads were not yet understood.

They are understood well enough now. Every deferred feature needs the same shape of thing: work that must happen after a database transaction commits, that may call a rate-limited external provider, that must survive a process dying halfway through, and that must not run twice in a way that duplicates records.

## Decision

**The durable record is the decision. The delivery mechanism is a detail.**

A `task_dispatch` row in PostgreSQL is the authoritative statement that work is owed. It is written in the same transaction as the business change that owes it, and it is the only thing any part of the platform treats as true. Nothing else — not a queue, not a scheduler, not a message — is a system of record.

That is the whole of the architectural commitment, and it is what the rest of this ADR is arranged to protect. It was chosen because it is the one decision that does not have to be revisited when the hosting plan, the provider, or the traffic changes.

Concretely:

1. **The dispatch table is the transactional outbox.** `uow.tasks.dispatch(...)` stages an insert in the caller's open transaction, exactly as `uow.audit.record(...)` already does. No network call happens inside a business transaction. Work is owed if and only if the change that justified it committed.
2. **Delivery is a replaceable adapter.** Application code calls a port that names no topic, endpoint, schedule, or vendor. An architecture test asserts the port's exact signature, so adding a `topic` argument fails the build.
3. **Execution is claim-and-run.** A runner leases due rows with `FOR UPDATE SKIP LOCKED`, runs the registered handler, and records the outcome in a separate transaction from the handler's own work.
4. **Reconciliation is the same query, not a second mechanism.** A lease is a deadline on the row rather than a lock held by a process, so a row abandoned by a killed invocation is simply due again. There is no reaper to write, and no reaper that can itself fail.
5. **Task types are a controlled vocabulary.** A row names a handler registered in Python at composition time. There is no dynamic import, no module path in a payload, and no fallback that guesses.
6. **The scheduled trigger is a Vercel Cron Job calling an authenticated internal endpoint.** That endpoint accepts no task type, payload, identifier, or batch size. It reads exactly one thing from the request: the `Authorization` header.
7. **Vercel Queues is the named upgrade path, not the v1 mechanism.** It is metered infrastructure requiring an owner decision, and it is documented below so that adopting it later is an adapter, not a redesign.

## Evidence

Gathered from current official Vercel documentation on 23 August 2026, not from memory or from secondary sources.

### Vercel Functions

| Limit | Hobby | Pro |
|---|---|---|
| Max duration | 300s default **and maximum** | 300s default, 800s max, 1800s extended (beta) |
| Memory | 2 GB / 1 vCPU | up to 4 GB / 2 vCPU |
| Request/response body | 4.5 MB | 4.5 MB |

300 seconds is ample for a batch of ordinary tasks and nowhere near enough for archive generation over a large scope. That informs the batch limit and the lease duration, both of which are configuration.

### Vercel Cron Jobs

- **Included on all plans**, including Hobby.
- **Hobby is limited to once per day**, and a more frequent expression *fails deployment*. Pro and Enterprise allow once per minute.
- **Hobby scheduling is approximate**: "Vercel cannot assure a timely cron job invocation." An expression of `0 1 * * *` fires anywhere between 01:00 and 01:59.
- Vercel issues an **HTTP GET** to the path, **on the production deployment URL only**.
- Authentication is a `CRON_SECRET` environment variable, sent automatically as `Authorization: Bearer <value>`.
- **"Vercel will not retry an invocation if a cron job fails."**
- Delivery is best effort: a run can be **missed**, and the same scheduled run can be **invoked more than once**. Vercel's own guidance is to make cron work "idempotent and reconciliation-based".
- There is no `vercel dev` support, so local runs go through the endpoint or the CLI directly.

Two consequences follow, and both are designed for rather than worked around. Because cron neither retries nor guarantees delivery, the *cron job cannot be where reliability lives* — the durable row is. And because a run may be duplicated or overlap a previous one, claiming has to be atomic, which is what `SKIP LOCKED` provides.

### Vercel Queues

Genuinely capable, and genuinely a Python option — which was the surprise, and the reason this section is longer than a rejection would warrant.

- A first-party Python SDK exists: `vercel-queue`, on PyPI at **0.8.0**, released **12 August 2026**, `requires-python >=3.10`.
- **At-least-once delivery**, visibility-timeout leases (60s default, 60 min maximum), retention 60s to 7 days, delayed delivery up to 7 days, and idempotency-key deduplication for the full lifetime of a message.
- **Push consumers are air-gapped**: "the function is completely air-gapped from the internet. It has no public URL and can only be invoked by Vercel's internal queue infrastructure." Python subscribers are declared under `[[tool.vercel.subscribers]]` in `pyproject.toml` and compiled into private queue-triggered functions at build time.
- **No built-in dead-letter queue.** Poisoned messages are handled at application level.
- **Topics are partitioned by deployment ID by default**, so a deployment produces and consumes its own messages.
- Billed **per API operation**, metered in 4 KiB chunks, with idempotency-key sends charged at 2x. Regionally priced as Managed Infrastructure, and gated behind a "Permissions Required: Vercel Queues" notice.

### This account

The team is on the **Hobby** plan, confirmed from the Vercel API (`"plan": "hobby"`). Queues does not appear in the Hobby included-usage table, and the project has **no production deployment** — deliberately, following the Phase 1A-V cleanup.

## Why this decision and not another

**Vercel Queues would not have removed the need for the dispatch table.** This is the argument that decided it. Even with Queues, the outbox problem remains: publishing inside a business transaction risks a message for a change that rolled back, and publishing after the commit risks losing the message entirely. The standard fix is a durable row written transactionally and published afterwards — which is this design, with Queues as the publisher. Adopting Queues first would therefore have built the same table anyway, plus a paid dependency, plus seven transitive Vercel-owned packages, to solve a latency problem the platform does not yet have.

Deployment-ID partitioning sharpens that. Messages belong to the deployment that published them, which is excellent for schema-compatible rollouts and unsuitable for a record that must survive redeployment. The queue is a transport. The table is the truth.

**Cron's weaknesses stop being weaknesses once the table is authoritative.** No retry, approximate timing, occasional duplicate or missed runs — each of these would be alarming if the cron invocation *were* the work. It is not: it is a nudge to look at a table that is already correct. A missed run delays work; it does not lose it. A duplicated run finds the rows already claimed. That is why the once-per-day Hobby limit is a latency constraint rather than a correctness one, and why moving to Pro changes a configuration value rather than a design.

## Rejected alternatives

**Celery.** Vercel documents running it, and on Vercel it is a wrapper over Vercel Queues (`broker="vercel://"`) rather than a worker process. It would inherit every cost of Queues and add its own: with Celery's default `task_acks_late = False` "a task that raises is never redelivered, and neither is one whose function times out while the task is still running", and even with `task_acks_late = True` "a task that raises is still acknowledged". Its result backend on Vercel is Runtime Cache, which the documentation calls "regional and ephemeral". Celery's real value is a mature worker runtime, and that is precisely the part Vercel replaces. Rejected as complexity that buys nothing here.

**Redis or RabbitMQ.** A new paid always-on service, new credentials, new failure modes, and a second system of record, to replace a table that already exists in a database we already run. Rejected. `SELECT ... FOR UPDATE SKIP LOCKED` is a well-understood queue primitive and PostgreSQL is already a hard dependency.

**An external always-on worker.** The honest fallback if drain latency ever becomes the binding constraint, and unnecessary now. It also reintroduces a permanently running host, which ADR 0002 removed on purpose. Kept in reserve: Vercel Queues poll mode explicitly supports off-platform consumers, so this stays open.

**Vercel Workflows.** Aimed at durable multi-step orchestration with `sleep()` over long spans. Plausible for archive generation later; far too large an abstraction for "run this handler soon", and it would put a vendor's programming model in the middle of application code.

**Treating the queue as the system of record.** Rejected for the reasons above: it does not survive redeployment, it cannot be joined against business data, and it cannot be made atomic with a database transaction.

**A dispatcher that publishes during the business transaction.** Rejected outright. It puts a fallible network call inside a transaction, which is the exact failure the outbox exists to prevent, and it makes transaction duration depend on a third party's availability.

## State machine

Six states, and the two that were considered and dropped matter as much as the six kept.

```
PENDING ──claim──> CLAIMED ──success──> SUCCEEDED
   │                  │
   │                  ├──retryable, attempts left──> PENDING (with backoff)
   │                  ├──retryable, attempts spent─> EXHAUSTED
   │                  └──not retryable────────────> FAILED
   └──cancel──> CANCELLED
```

`DISPATCHED` and `RUNNING` were dropped. Under this runtime a claimed row is both at once and nothing can observe the difference: the claim is what hands the work over, and the lease is what proves someone is still working on it. A state the system cannot distinguish is a state that will eventually lie.

`FAILED` and `EXHAUSTED` are deliberately separate. Refused means this code can never run this row, so nobody should be paged. Exhausted means it could have, and work was genuinely lost. Only the second is an operational alarm.

## Delivery semantics

At-least-once, assumed rather than hoped for. Every candidate runtime provides it, cron duplicates runs, and a lease can expire while a handler is still working. Handlers are therefore idempotent, and the platform provides two levers:

- **Dispatch-side**: an `idempotency_key` with a database unique constraint. Two requests deriving the same key produce one task, and the duplicate does not abort the caller's transaction.
- **Execution-side**: `TaskContext.attempt`. Any value above 1 means a previous attempt did not finish, so a handler that is not naturally idempotent can check before acting.

Exactly-once distributed execution is not attempted, and no part of the design pretends otherwise.

## Security

- The drain endpoint takes **no input** beyond `Authorization`. "Run an arbitrary task" is not a request it can express, so it is a structural property rather than a validation rule that a later refactor could weaken.
- Authentication is a shared secret compared with `secrets.compare_digest`. An unconfigured secret **denies everything**, and the denial is byte-identical to a wrong secret, so probing reveals nothing about whether background processing is switched on.
- Task types resolve only through the registry. Even a row written directly into the database can name nothing this deployment did not register in Python.
- Payloads carry internal identifiers and scalars. Sensitive field names, nested objects, and oversized strings are refused by the domain before a row exists.
- Failures persist a short slug, never an exception message or traceback. Both routinely quote the value that caused them, and the payload sits one column away.
- **Authorization is revalidated at execution.** A task may wait a long time, during which a grant can be revoked or an account suspended. `AUTHORIZATION_INVALIDATED` is a terminal failure kind so that losing permission is recorded rather than retried.
- Inline dispatch **cannot be constructed in a deployed environment**. It raises rather than warning, mirroring the hosted-environment rule in ADR 0002 and for the same reason: the weakest behaviour must not also be the quietest.

## What is verified, and what is not

**Verified locally against real PostgreSQL 17**: the migration applies, reverses, and reapplies; the model matches the migrated schema with no drift (`alembic check`); dispatch is atomic with business writes and disappears on rollback; duplicate idempotency keys record one task without poisoning the transaction; two concurrent connections never claim the same row; expired leases are reclaimed; the retry lifecycle reaches `EXHAUSTED`; and the `flask tasks` commands work on Windows.

**Not verified on Vercel, and deliberately not.** Cron jobs invoke the production deployment URL, and this project has no production deployment. Creating one to test a scheduler would mean promoting an application with no managed database and no production secrets, which is exactly what the Phase 1A-V cleanup removed. The endpoint itself is ordinary HTTP and is fully tested; what remains unproven is the wiring between Vercel's scheduler and it.

## Owner actions required before background work runs in a deployment

Not taken here, because each is an account-level or billing decision.

1. **A production deployment must exist** before any cron job can fire. This is a promotion decision, not a side effect of this ADR.
2. **Set `TASK_RUNNER_SECRET`** in the deployment environment, and set `CRON_SECRET` to the same value so Vercel's automatic `Authorization` header matches. Until then the endpoint denies everything, which is the intended inert state.
3. **Add the cron entry** to `vercel.json` (no such file exists yet, by design). On Hobby the schedule may fire at most once per day; anything more frequent fails the deployment.
4. **Decide about the plan.** Once-per-day reconciliation is too slow for Classroom sync or notification fan-out to feel responsive. Pro raises this to once per minute and is the natural trigger for that upgrade. Separately, Vercel's fair-use guidelines restrict Hobby to "non-commercial, personal use only", which is worth resolving before this platform serves an institution regardless of scheduling.
5. **Vercel Queues remains unenabled.** Adopting it later means writing one adapter behind the existing port and publishing from the drain, not changing any application code.

## Consequences

- The blocker recorded in Phase 1A is lifted. Features may now express work that outlives a request.
- Background latency on the current plan is up to roughly a day. Features must be designed to tolerate that or wait for the plan decision, and neither is a correctness problem.
- PostgreSQL takes on queue traffic. Claim queries are indexed on both branches, and terminal rows never match either predicate, but pruning succeeded rows will eventually be needed. `completed_at` exists for that.
- Every handler carries an idempotency obligation, permanently, and reviews should treat it as such.
- The runtime can change without touching application code. That is the property this ADR exists to buy, and the architecture tests are what stop it eroding.
