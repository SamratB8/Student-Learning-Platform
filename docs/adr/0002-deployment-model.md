# ADR 0002: Deployment Model and Production Hosting

- Status: Accepted
- Date: 21 August 2026
- Supersedes: the always-on process and self-managed reverse proxy assumptions in ADR 0001 and ARCHITECTURE.md
- Decision basis: owner-approved hosting decision after Phase 0

## Context

ADR 0001 selected a Flask modular monolith with "a separate worker process" and left the runtime open. ARCHITECTURE.md described a deployment with a self-managed reverse proxy and a colocated queue worker, which implies a permanently running Linux host.

The owner has decided that the production web target is Vercel. Local development stays Windows-native with Docker Desktop for development services. This changes the runtime shape of the application even though it does not change the stack or the domain design.

## Decision

Production web hosting is Vercel. The application is therefore designed for serverless request handling, with all durable state external.

1. The web application is a WSGI application produced by an application factory. There is no module-level `app = Flask(...)` singleton holding state, no background thread started at import, and no in-process scheduler.
2. Nothing may depend on process lifetime. In-process caches, locks, counters, rate-limit state, and session stores are invalid unless they are pure per-request derivations or explicitly backed by an external store.
3. The filesystem is ephemeral and effectively read-only. Uploads, exports, archives, and generated artefacts go to object storage. Temporary files may exist only within one request.
4. PostgreSQL is an external managed service. The application must tolerate many short-lived invocations opening connections. Pool sizing and any connection pooler are deployment configuration, not application assumptions.
5. Object storage is external, private, and S3-compatible.
6. Matrix is deployed separately and is never colocated with the web application.
7. Background work is expressed against a task-dispatch port. No always-running colocated worker is assumed. The concrete runtime is deferred to ADR 0004.
8. TLS, security headers, rate limiting, and request size limits are enforced by the hosting edge together with application configuration, not by a self-managed reverse proxy.
9. All configuration and secrets come from environment variables. Deployment-specific product values, such as institutions and branches, remain configuration data.

## Deferred deliberately

No `vercel.json` and no serverless entry module are created in Phase 1A. The application factory is the only thing needed to make a future entry point trivial, and adding untested deployment configuration now would be speculation rather than readiness. The entry point is created in the task that performs a real preview deployment and can validate it.

## Consequences

- The architecture stays a modular monolith. Only the runtime changes.
- Any feature requiring work longer than one request must wait for ADR 0004. This is a real constraint on Classroom synchronization, indexing, malware scanning, notification fan-out, and archive generation.
- Database access patterns matter earlier than they otherwise would, because connection churn is higher than with a long-lived process.
- Development and production runtimes differ. The Flask development server is never a production runtime, and code must not rely on behavior unique to it.
- Integration failures still must not fail authorization open. Serverless retries make idempotency more important, not less.

## Rejected alternatives

- A permanently running Linux host with a reverse proxy and colocated worker: rejected because the owner has selected Vercel and maintaining a second production runtime is not justified for a small team.
- Deploying the web application to Vercel while quietly assuming a colocated worker anyway: rejected because it produces code that cannot run in the target environment.
