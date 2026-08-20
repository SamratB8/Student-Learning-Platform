# Repository Instructions

## Authority and scope

The Markdown files in `docs/` define the frozen v1 baseline. If implementation ideas conflict with them, stop and propose a documented change; do not silently reinterpret the product.

This software is privately owned and institution-neutral. CTS is the first deployment configuration only. Do not imply CTS sponsorship or hard-code CTS, DCST, DME, DEE, DCE, diploma, semester counts, branding, or institution-specific identifiers in domain logic.

## Current phase

Phase 0 is complete pending owner review/commit. Begin only Phase 1 foundation when instructed; do not jump ahead to user-facing product features.

## Non-negotiable decisions

- Google OAuth authentication plus manual Super Admin approval; no password or OTP authentication.
- Separate, required Google Classroom connection with persistent non-blocking reminders.
- Four CTS Classroom logical pools configured as DCST, DME, DEE, and DCE; shared object bytes may be deduplicated without widening permissions.
- Platform-owned academic records, three canonical note categories, student contributions, versions, protected view/download, and explicit provenance badges.
- Platform-owned routine/events with Google Calendar sync and Google Meet for live calls.
- Matrix backend and supported crypto/SDK with a custom platform UI; do not build a messaging server or cryptographic protocol and do not use Element as the main UI.
- Platform owns groups/membership/permissions; Matrix owns room/message/encrypted-media infrastructure.
- Permission-filtered global search; E2EE message plaintext is not server-indexed.
- Mobile-usable admin, in-app notifications, security audit trail, archive/export, and a clean BTech transition.
- ChatGPT integration is one-way draft ingestion. It cannot read, publish, update arbitrary records, delete, or administer. Never automatically send member data to AI.

## Engineering rules

- Deny authorization by default and enforce it server-side.
- Keep provider code behind adapters and domain rules provider-independent.
- Use generated internal IDs and typed external IDs.
- Treat provider payloads, uploads, and AI drafts as untrusted data.
- Never put secrets, tokens, signed URLs, private keys, message plaintext, or sensitive payloads in source or logs.
- Migrations are forward-reviewed and tested; do not edit already-released migrations.
- Every change includes proportionate unit/integration/security denial tests, docs, and migration/config updates.
- Do not add a service or dependency without recording why it is necessary, maintained, licence-compatible, and preferable to existing choices.
- Do not claim E2EE or official institutional status without the documented gates and evidence.
- Treat `LICENSE` as authoritative. Repository access is not permission to use,
  copy, modify, distribute, host, or create derivatives outside an explicit
  written and signed Permission Document from the copyright owner.

## Definition of done

Relevant tests and static checks pass; authorization denial cases are covered; migrations/config are safe; secrets are absent; accessibility and mobile behavior are considered; documentation matches behavior; and external failures do not fail authorization open.
