# Security Model

## Trust boundaries

- The public internet and every browser request are untrusted.
- Google authentication proves control of a Google identity at that time; it does not grant platform membership.
- Manual approval grants a platform status, not blanket authorization.
- Google, Matrix, object storage, and ChatGPT draft requests cross external trust boundaries.
- Super Admin is powerful but is not a universal Matrix decryption identity.

## Protected assets

- Student identity/contact data and approval notes.
- Roles, grants, branch/group membership, and session state.
- Restricted academic resources and signed access links.
- Google tokens, Matrix credentials/keys, draft-receiver secrets, encryption keys.
- Message ciphertext, encrypted media, device identity state, and limited metadata.
- Audit records, backups, archives, and integration payloads.

## Principal threats

- Account takeover, OAuth login CSRF/state substitution, stolen refresh tokens, and session fixation.
- IDOR/BOLA and branch/group scope bypass.
- Malicious uploads, MIME spoofing, stored XSS, unsafe previews, malware, path traversal, and decompression bombs.
- Provider spoofing, webhook replay, duplicate processing, confused-deputy integration behavior.
- Matrix room/member drift that exposes a room to an unauthorized platform member.
- Secret leakage through source, logs, errors, backups, or client bundles.
- Admin privilege escalation, unsafe bulk export, audit tampering, and insider misuse.
- Prompt/content injection through the ChatGPT receiver; a draft is untrusted content, not an instruction.
- Over-collection or leakage through an AI path: retrieving more context than the user may see, or sending private data to a provider.
- Device capability data used as a covert fingerprint or as a basis for an authorization decision.

## Required controls

### Identity and sessions

- Authorization Code flow with PKCE, state, nonce, exact redirect allowlists, and server-side token exchange.
- Secure, HttpOnly, SameSite cookies; short sessions with rotation and server-side revocation.
- Re-authentication for role changes, exports, destructive administration, and credential changes.
- Rate limits and anomaly visibility on login, application, approval, token refresh, and recovery paths.
- Never interpret a Google domain or Classroom membership as automatic approval.

### Authorization

- Deny by default. Evaluate account state, capability, scope, resource audience, and ownership server-side for every request.
- Use stable internal IDs; never trust branch/group/provider IDs submitted by the client without authorization lookup.
- Test positive and negative cases across global, branch, subject, group, self, and public scopes.
- Signed object URLs are short-lived, purpose-bound, and issued only after a fresh policy check.

### Data and uploads

- Validate extensions, MIME signatures, size, archive depth, and media dimensions; rename objects to generated IDs.
- Quarantine uploads until required checks complete. Serve active content with safe content-disposition and isolated origins where applicable.
- Encrypt disks/backups and sensitive tokens at application/key-management boundaries.
- Separate environments, buckets/prefixes, credentials, and databases.
- Define retention and deletion by data class; backups must have documented expiry and restore tests.

### Integrations

- Request minimum Google scopes incrementally; Classroom consent is separate from login consent.
- Encrypt provider refresh tokens and record consent/scopes/expiry/revocation without logging token values.
- Verify webhook/request signatures where supported, replay windows, event IDs, and idempotency keys.
- Matrix provisioning credentials never reach browsers. Reconcile platform group membership against Matrix room membership.
- Treat ChatGPT-submitted text/files as hostile uploads. Authenticate, rate-limit, schema-validate, quarantine, and create drafts only.

### Messaging truthfulness

- Use supported Matrix cryptography; never implement custom cryptographic algorithms.
- Define device addition/removal, verification, recovery, backup, key change, and lost-device flows before launch.
- Do not log or server-index plaintext. Notifications use privacy-safe wording.
- Advertise E2EE only after encrypted-room defaults, membership-change tests, multi-device behavior, key storage/recovery, and an independent security review pass.

### AI privacy boundary

- Authorization runs before retrieval, and retrieval runs before any content reaches an external AI provider. An authorization failure stops the flow rather than degrading into unfiltered retrieval.
- Never send to any AI provider, automatically or otherwise: direct messages, Matrix message history, group chat plaintext, phone numbers, email addresses, approval records, authentication or session data, OAuth tokens, Matrix keys, administrative or audit records, or unrelated personal information.
- The internal AI utility is server-side infrastructure. It is not reachable from any student-facing route, and its credentials never reach a browser.
- The Continue in ChatGPT handoff is clipboard-based. The platform never authenticates to, calls, or automates a student's ChatGPT account, and no user-supplied provider key is accepted.
- Every AI-assisted path has a defined deterministic result. Provider failure degrades polish, never correctness or authorization.
- Treat model output as untrusted content, exactly like a provider payload or an upload. It is never an instruction and never a source of authorization.

### Devices and capability profiles

- A device installation is identified by a randomly generated, revocable identifier supplied by the client. Invasive hardware fingerprinting is prohibited.
- Capability measurement heavy enough to be noticeable requires informed consent and must not run on every visit.
- A capability profile influences whether optional on-device work is offered. It never influences an authorization decision.
- A user can see and revoke their own installations.

### Client and hosting boundaries

- Secrets, provider credentials, and service keys never appear in templates, frontend bundles, source maps, or client-readable configuration.
- The production runtime filesystem is ephemeral and untrusted for persistence. Security state is never held in process memory or on local disk between requests.
- Security headers, TLS, rate limits, and request size limits are enforced by the hosting edge together with application configuration, and each environment is verified independently.

### Audit and operations

- Record actor, action, target type/ID, scope, time, result, reason category, request/correlation ID, and source IP classification where justified.
- Exclude passwords, OAuth codes/tokens, cookies, private keys, message plaintext, signed URLs, and full sensitive payloads.
- Make audit storage append-oriented with restricted deletion and integrity monitoring.
- Maintain tested backup/restore, incident response, credential rotation, dependency patching, and vulnerability management runbooks.

## Security release gates

- Threat model and data classification reviewed.
- Permission matrix has automated denial tests.
- OAuth and session review complete.
- Upload pipeline and protected download tests complete.
- Matrix E2EE claim gate complete before marketing claims.
- Integration secret scan and log-redaction tests pass.
- Archive/export privacy review and restore test pass.
- AI privacy boundary tested: authorization precedes retrieval, excluded data classes cannot enter a prompt, and every AI path has a verified deterministic fallback.
- Accessibility review complete: keyboard-only operation, visible focus, contrast, reduced motion, and narrow-viewport usability on every user-facing surface.
