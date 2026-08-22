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
7. Background work is expressed against a task-dispatch port. No always-running colocated worker is assumed. ADR 0004 selects the runtime: a durable dispatch table in PostgreSQL, drained by a scheduled invocation.
8. TLS, security headers, rate limiting, and request size limits are enforced by the hosting edge together with application configuration, not by a self-managed reverse proxy.
9. All configuration and secrets come from environment variables. Deployment-specific product values, such as institutions and branches, remain configuration data.

## Verification (Phase 1A-V, 21 August 2026)

The decision was validated by an actual Vercel preview deployment rather than by reasoning about it. What follows was observed, not assumed.

**Entry point.** `wsgi.py` at the repository root exposes `app = create_app(load_hosted_settings())`. `pyproject.toml` names it through `[tool.vercel] entrypoint = "wsgi:app"`, which Vercel documents as the approach for new projects. Filename auto-detection would also have worked, but is left unused because this repository has a `src` layout and Vercel scans `src/` for entrypoint filenames too. The adapter contains no configuration, no routes, and no logic; `create_app` remains the single composition root.

**Python version.** Vercel supports 3.12 (default), 3.13, and 3.14. The build reported `Using Python 3.14 from .python-version`, and the application's own startup log recorded `python_version: 3.14.6` at runtime, matching local development exactly. No version declaration was added: the existing `requires-python` and `.python-version` were already sufficient.

**Dependencies.** The build reported `Installing required dependencies from uv.lock`. Vercel consumes the uv lockfile natively, so the deployed dependency set is the locked one. No `requirements.txt` is needed, and none was added.

**No `vercel.json` was required.** Zero-configuration deployment worked. One is added only when something concrete needs it, such as a `maxDuration` change or bundle exclusions.

**Fail-fast configuration held.** A boot with an invalid variable produced `FUNCTION_INVOCATION_FAILED` and no served requests, which is the intended behavior from point 9 above. Requiring `DATABASE_URL` in deployed environments was confirmed as deliberate and was not relaxed to make a preview succeed.

**Health semantics under a serverless runtime.** `/healthz` answered 200 while no database existed; `/readyz` answered 503 with `database: unavailable`. Liveness and readiness stay genuinely independent, so a database outage cannot cause a restart loop.

**Cold start.** Roughly 0.75s cold against 0.56–0.62s warm, with the application built once per function instance at import. That is the intended serverless shape: the object holds no request-scoped state.

**A defect was found and fixed.** The failed boot printed the chained pydantic `ValidationError` into Vercel's runtime logs, and that rendering echoes each rejected value, including part of `DATABASE_URL`. Sanitising the `ConfigurationError` message alone was not enough because a `__cause__` is rendered in full by any traceback. The cause is now suppressed, and a regression test renders the traceback the same way a runtime does. Re-verified on a preview: the failed boot names the offending variable and discloses no value.

## Invariant: a hosted deployment may never silently fall back to development mode

Added 22 August 2026, after the first deployment of this project breached it.

Vercel assigns a brand-new project's first deployment to the production target regardless of flags. That deployment carried no `APP_ENV`, so the application used its development default and served a public URL with development error verbosity, non-secure session cookie settings, and a `/readyz` that answered 200 "ready" while nothing was configured. Nothing failed. The weakest posture was also the quietest one, which is what made it dangerous.

The rule now applied at startup, in `infrastructure/config/hosting.py`:

| Situation | Result |
|---|---|
| No hosting marker, no `APP_ENV` | development, unchanged local behaviour |
| No hosting marker, explicit `APP_ENV` | that environment |
| Hosted, platform reports `production` | production |
| Hosted, platform reports `preview` | staging |
| Hosted, platform reports `development` (`vercel dev`) | development, an explicit platform statement rather than a fallback |
| Hosted, explicit `APP_ENV` that is `development` or `test` | **refused** |
| Hosted, platform reports nothing recognisable, no explicit `APP_ENV` | **refused** |

Preview maps to staging rather than to a preview-specific environment because staging already carries production strictness, and a preview is reachable over the internet.

Only server-side environment variables are consulted. Resolution happens once at startup, before any request exists, so a request header cannot reach the decision even in principle. `VERCEL_ENV` is the signal used because its value set is closed; `VERCEL_TARGET_ENV` is not, since it may hold an arbitrary custom environment name.

Detection treats any one Vercel marker variable as proof of hosting rather than requiring all of them, because requiring all would fail open the moment one was withheld. Every such marker depends on the project's "system environment variables" setting, so the hosting entry point additionally asserts hosted execution through `load_hosted_settings` instead of relying on detection: being imported at all proves a platform imported it.

Verified on a live preview with `APP_ENV` deleted entirely. The application resolved to `app_env: staging`, `debug: false`, and sent its own HSTS header, where the old behaviour would have produced development.

## Still deferred

- Static assets. Vercel serves `public/**` from its CDN, and Flask's `static_folder` must not be used. With no `public/` directory, every path routes to the function, which was confirmed by requesting a `.css` path and receiving the application's own JSON 404. Publishing the design tokens belongs with the first page that uses them.
- Deriving `APP_BASE_URL` per preview deployment. It is currently a fixed project URL, which is correct for production but not for a per-deployment preview URL. `VERCEL_URL` is an environment variable rather than a request header, so reading it would not violate the rule against trusting request-supplied origins.
- Managed PostgreSQL, connection pooling strategy, object storage, and a custom domain.
- Attaching the scheduled background drain. ADR 0004 chose the mechanism and it is tested, but Vercel Cron invokes the production deployment URL only, so it cannot be wired up while the project deliberately has no production deployment.
- A production deployment. The accidental one was removed on 22 August 2026 and the project deliberately has none, no Production environment variables, and a production URL that answers `DEPLOYMENT_NOT_FOUND`. Promotion is a decision to take when the product is ready for it, not a side effect of a first deploy.

## Consequences

- The architecture stays a modular monolith. Only the runtime changes.
- Work longer than one request goes through the durable dispatch table selected in ADR 0004, which is now accepted. The remaining constraint is scheduling rather than architecture: a drain must be triggered, and on the current plan that can happen at most once a day.
- Database access patterns matter earlier than they otherwise would, because connection churn is higher than with a long-lived process.
- Development and production runtimes differ. The Flask development server is never a production runtime, and code must not rely on behavior unique to it.
- Integration failures still must not fail authorization open. Serverless retries make idempotency more important, not less.

## Rejected alternatives

- A permanently running Linux host with a reverse proxy and colocated worker: rejected because the owner has selected Vercel and maintaining a second production runtime is not justified for a small team.
- Deploying the web application to Vercel while quietly assuming a colocated worker anyway: rejected because it produces code that cannot run in the target environment.
