# Integrations

## General rules

- Platform-owned data remains usable when an integration is temporarily unavailable.
- Providers are isolated behind adapters and configured per deployment.
- OAuth scopes are incremental and minimal.
- Tokens and service credentials are encrypted and redacted from logs.
- Webhooks/events are authenticated where supported, replay-protected, idempotent, and reconciled by periodic jobs.
- Provider content is untrusted input and never treated as operational instructions.

## Google OAuth

Purpose: authenticate a Google identity. It does not approve membership.

Flow: OAuth Authorization Code + PKCE -> identity lookup/create -> application/status check -> platform session. Classroom and Calendar permissions are requested separately when the user connects those features.

## Google Classroom

Purpose: surface teacher materials, assignments, announcements, attachments, links, and deadlines accessible to the connected student.

Required behavior:

- Persistent, non-blocking reminders until an approved student has a healthy Classroom connection.
- Four CTS logical pools: `classroom-dcst`, `classroom-dme`, `classroom-dee`, `classroom-dce`.
- Course mapping is suggested where possible and confirmable; confirmed mapping is reused for the same external course.
- Many user connections may provide access evidence, but external course/item identity is normalized once.
- Linked mode preserves the original as authority. Imported mode is explicit, permission-aware, checksum-deduplicated, and retains the original reference.
- Source badges and provenance are mandatory.
- v1 reads learning information only; submissions and grades stay in Classroom.

Revocation or expiry stops future sync and re-enables reminders. It must not silently delete previously published/imported records; retention and access decisions are reviewed separately.

## Google Calendar

Purpose: synchronize selected academic events/deadlines while the platform remains authoritative for its event model.

Store provider calendar/event references, direction, etag/version, last attempt/success, and error state. Conflict behavior must be explicit per event type. Never infer that every personal Calendar event may be read or imported.

## Google Meet

Purpose: live calls associated with events, groups, or conversations.

The platform controls who can see a meeting entry and audits link changes. Google controls media, admission, and service logs. Display an external-service notice before opening Meet. Meet is not covered by Matrix E2EE claims.

## Matrix

Purpose: DMs, group chat, delivery/sync, reactions, replies, receipts, and encrypted attachments/media behind a custom platform UI.

- Use a supported client SDK and supported cryptographic implementation.
- Platform users/groups remain authoritative; store only necessary Matrix IDs and provisioning/reconciliation state.
- Service provisioning credentials remain server-side.
- Reconcile room membership after group changes and surface failures to operators.
- Do not duplicate message plaintext in PostgreSQL or server search.
- Encrypted message search is client-local where required.
- E2EE launch and claim are gated by the security model.

## One-way ChatGPT draft receiver

Purpose: receive work the owner deliberately supplies to ChatGPT and have it returned as a platform draft.

Allowed operations: submit a new note/resource/notice/event/file draft and receive a submission acknowledgement/reference.

Forbidden operations: list/read/search platform data, read users, update arbitrary records, publish, delete, grant permissions, trigger integrations, or retrieve prior drafts.

Every request is authenticated, rate-limited, schema/size validated, malware-scanned where applicable, idempotent, and audited. Content enters quarantine or `DRAFT`; a human reviews it. No platform process automatically sends private/member data to an AI provider.

## Failure policy

Integration failures are visible and retryable. Core authorization does not fail open. A failed Calendar write leaves a marked platform event; a failed Classroom sync leaves last-known data with freshness status; a failed Matrix membership operation blocks or rolls back exposure and alerts an operator; a failed draft submission creates no partial published content.
