# Product Requirements - Frozen v1 Baseline

## Product promise

The platform is a privately operated digital home where an approved student community can find academic material, notices, schedules, events, groups, and private conversations in one consistent interface. The software remains institution-neutral; CTS is the first deployment configuration, not the product owner.

## v1 users

- Public visitors: see explicitly published public information and the ownership disclaimer.
- Pending applicants: sign in, complete their application, and see approval status.
- Approved members: use content and collaboration permitted by their scopes.
- Scoped moderators and branch admins: manage delegated content and communities without global authority.
- Super Admin/Owner: approve accounts, manage configuration, security, audit, archives, and scoped roles; this role does not imply access to encrypted message plaintext.
- Draft publishers: tightly restricted machine identities that may submit drafts but cannot publish or read platform data.

## Required capabilities

### Identity and entry

- Authenticate with Google OAuth; do not create a password, email OTP, SMS OTP, or mobile OTP system.
- Treat Google authentication and platform authorization as separate decisions.
- Collect the minimum application profile needed for manual identity review: Google identity, name, mobile number, student/roll number, branch, and optional note.
- Require manual approval before private/member access.
- Support `PENDING`, `APPROVED`, `REJECTED`, `SUSPENDED`, `DISABLED`, and `ARCHIVED` lifecycle states.

### Required Google Classroom connection

- Every approved student is expected to connect Google Classroom using separately requested, minimal OAuth scopes.
- A missing Classroom connection does not completely lock the site. It creates a persistent dashboard banner, notification item, onboarding task, and contextual reminders in Resources, Assignments, and Calendar.
- Stop reminders after a healthy connection is established; restore them when consent or access expires.
- Normalize each Google course once and reuse the mapping across students who share the same Classroom course.
- Keep four logical ingestion/catalogue pools for the CTS deployment: DCST, DME, DEE, and DCE.
- Pools are permission boundaries, not necessarily four physical copies. Identical stored objects may be checksum-deduplicated while their branch-scoped records remain distinct.
- Support linked and explicitly imported Classroom resources. Preserve original URLs, item/course IDs, timestamps, source owner where available, and synchronization status.
- Ingest permitted materials, assignments, announcements, attachments, links, and due dates. Classroom remains authoritative for submission and grades in v1.

### Academic resources and notes

- Organize resources by institution, programme, branch, cohort/batch, term/semester, subject, topic, type, source, version, visibility, and moderation state.
- Keep view and download permission separate.
- Support provenance badges for Google Classroom teacher material, institution-provided material, official/government material, books/references, community contributions, and platform-curated notes.
- Implement three canonical note categories as first-class records:
  1. `COLLEGE_ONLY`: college-provided sources only.
  2. `COLLEGE_AND_OFFICIAL`: college plus verified official/council/government sources.
  3. `COMPREHENSIVE`: the preceding sources plus lawful references and reviewed useful additions.
- Community submissions remain contributions until reviewed; they never silently change a canonical note.
- Preserve source links, version history, authorship, review, and publication state.

### Schedule, Calendar, and Meet

- Store notices, timetable/routine entries, deadlines, and events in the platform's own data model.
- Offer a custom platform calendar with optional Google Calendar synchronization and explicit sync state/error handling.
- Use Google Meet for live calls. The platform stores and permission-checks meeting context/links; Google handles the live media.
- Clearly tell the user before opening Google Meet and never imply platform message encryption covers a Meet call.

### Messaging and groups

- Use a Matrix homeserver and supported Matrix client SDK as messaging infrastructure.
- Build a custom platform interface; do not embed or expose Element as the primary UI.
- The platform owns users, group identity, membership, discoverability, moderation, and permissions. Matrix owns rooms, events, delivery, encrypted media, and supported E2EE behavior.
- Map platform users to Matrix identities and platform groups to Matrix rooms.
- Support DMs, group chat, replies, reactions, read/unread state, attachments, images, voice notes, recorded video notes, and client-capable message search.
- Use Google Meet, not MatrixRTC, for v1 live calls.
- Do not claim E2EE until the selected Matrix deployment, SDK crypto path, device lifecycle, recovery, and verification UX pass the security gate.
- Groups may be discoverable, private, or invite-only and may own resources, events, announcements, and one mapped Matrix room.

### Platform services

- Provide an in-app notification center with privacy-safe message previews, user preferences, and reliable Classroom-connection reminders.
- Provide permission-filtered global search across resources, notes, notices, events, groups, and permitted user fields. Encrypted message search stays client-side/local where required by Matrix E2EE.
- Provide a mobile-usable admin portal for approvals, roles/scopes, academics, content, groups/reports, integrations, configuration, system health, and audit.
- Audit sensitive administrative and integration actions without logging secrets or message plaintext.

### One-way ChatGPT draft receiver

- Accept authenticated draft submissions from ChatGPT for notes, resources, notices, event drafts, and files.
- The credential may create a draft only. It cannot read users/data, publish, update arbitrary records, delete, or administer.
- Never send platform user data or stored private content to ChatGPT automatically.
- A human must review and publish every received draft.

### Archive and BTech transition

- Export permitted academic/public history with a manifest, versions, provenance, and checksums before the CTS period ends.
- Do not include private messages or unrelated personal data in a central archive.
- Allow users to export their own contributions and, if supported by their Matrix clients and consent policy, their own conversation history.
- Treat BTech as a fresh deployment/tenant configuration with new branding, programmes, scopes, policies, approvals, and retention decisions.
- Do not automatically carry CTS approvals, private groups, message histories, restricted files, or branding into BTech.

## Non-goals for v1

- Acting as an official CTS system or using protected institutional branding without permission.
- Password authentication, OTP verification, grade management, or Classroom assignment submission.
- Building a messaging server, encryption protocol, live-call service, or video conferencing stack.
- Automatic AI reading, summarization, or training on platform/member data.

## Product acceptance rules

- Server-side authorization is tested; hidden UI controls are never treated as security.
- Unclear visibility defaults to member-only.
- Institution names, branch sets, branding, policies, and external IDs are configuration.
- Every imported or curated academic item has explainable provenance.
- External integration failures degrade independently and visibly without corrupting platform-owned data.
- Security claims match demonstrated behavior.
