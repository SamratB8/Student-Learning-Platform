# Data Model

This is the conceptual v1 model. Physical schema design and migrations begin after the stack decision.

## Conventions

- Use generated internal IDs; provider IDs are typed external identifiers, never primary business keys.
- Every mutable domain record has creation/update timestamps and an explicit lifecycle/status where appropriate.
- Institution/branch names and codes are deployment data, not enum values in application code.
- Soft deletion is not a universal default. Retention behavior is explicit per entity and legal/product need.

## Identity and tenancy

- `Deployment`: isolated configuration and lifecycle boundary.
- `Institution`: institution presented by a deployment; relationship/disclaimer metadata is explicit.
- `Programme`, `Branch`, `Cohort`, `Term`, `Subject`, `Topic`: configurable academic hierarchy.
- `User`: platform person record, independent of provider identity.
- `ExternalIdentity`: provider, subject ID, verified email snapshot, last authentication time.
- `Application`: submitted profile, branch choice, state, decision metadata, private approval note.
- `Session`: revocable authenticated session metadata.
- `IntegrationConnection`: user/provider consent, encrypted token reference, scopes, health, expiry/revocation.

## Authorization

- `Role`: named convenience bundle such as Super Admin, Branch Admin, Moderator, Member.
- `Capability`: atomic action, for example `users.approve` or `resources.review`.
- `RoleCapability`: role-to-capability mapping.
- `Scope`: typed boundary (`GLOBAL`, `INSTITUTION`, `BRANCH`, `SUBJECT`, `GROUP`, `SELF`).
- `RoleGrant`: user, role, scope, grantor, validity, revocation.

## Academic content

- `StoredObject`: immutable object key, checksum, detected type, size, scan state, encryption/storage metadata.
- `Resource`: semantic item, academic scope, visibility, origin, source type, review/publication state, view/download policy.
- `ResourceVersion`: versioned metadata and optional stored object/link.
- `ProvenanceSource`: provider/source authority, original URL/ID, owner/teacher where available, dates, citation/licence metadata.
- `ResourceSource`: joins a resource version to one or more provenance sources.
- `CanonicalNote`: subject/topic and category (`COLLEGE_ONLY`, `COLLEGE_AND_OFFICIAL`, `COMPREHENSIVE`).
- `CanonicalNoteVersion`: draft/review/published version and change summary.
- `CanonicalNoteSource`: sources actually used by a note version.
- `Contribution`: separate student submission with review state.
- `MergeProposal`: reviewed suggestion connecting contribution material to a future canonical version; never an automatic merge.

## Classroom

- `ClassroomPool`: deployment + branch logical boundary; CTS seeds four records.
- `ClassroomCourse`: normalized external course identity and metadata.
- `ClassroomCourseAccess`: connection/user evidence that a course is accessible; expires/revokes independently.
- `ClassroomCourseMapping`: course to pool, subject, term, confidence, confirmation status, and approver.
- `ClassroomItem`: normalized material/assignment/announcement keyed by provider course/item identity.
- `ClassroomAttachment`: Drive/link/YouTube/Form/other attachment metadata.
- `ClassroomIngestion`: observed version, connection used, received/processed times, outcome/error.
- `ClassroomResourceLink`: maps normalized Classroom content to linked/imported platform resource(s).

Multiple students may provide access evidence to one course/item. This must not produce duplicate items or widen branch permissions.

## Scheduling

- `Notice`: audience, visibility, publication state, attachments.
- `Routine` and `RoutineEntry`: effective date range, recurrence/day, time, subject, optional room/instructor, scope, source attachment.
- `Event`: platform-authoritative title, schedule, recurrence, audience, visibility, status.
- `Deadline`: assignment/resource reference and due time.
- `CalendarSync`: provider calendar/event IDs, direction, etag/version, sync state/error.
- `MeetingLink`: provider, external reference/URL, visibility, creator, status; secrets are not stored here.

## Community and messaging

- `Group`: name, purpose/type, discoverability, scope, owner, status, Matrix room reference.
- `GroupMembership`: user, role, state, inviter/request decision, dates.
- `MatrixIdentityMapping`: platform user to Matrix user ID/provisioning state.
- `MatrixRoomMapping`: platform group/conversation reference to Matrix room ID and reconciliation state.
- `ContentReport`: reporter, referenced event/content, deliberately submitted evidence, state, decision. It is not a hidden plaintext archive.

Message events and encrypted media belong to Matrix and are not duplicated as platform message tables.

## Notifications, search, audit, and integrations

- `Notification`: user, category, safe payload/reference, read/dismissed state.
- `NotificationPreference`: category/channel, enabled, quiet hours/digest.
- `SearchDocument`: permitted non-E2EE index projection with audience/scope fields.
- `AuditEvent`: append-oriented actor/action/target/scope/result/reason/correlation metadata.
- `IntegrationEvent`: provider event ID, idempotency state, processing outcome.
- `OutboxEvent`: reliable pending platform-side integration work.
- `DraftSubmission`: restricted publisher, kind, untrusted payload/object, validation/quarantine/review state.
- `ArchiveJob`, `ArchiveManifest`, `ArchiveEntry`: scope, requester, state, checksums, retention/expiry.

## Critical invariants

- `APPROVED` status alone never grants a capability; it only allows grants to take effect.
- A resource cannot be downloaded merely because it can be viewed.
- Canonical note categories may include only source classes allowed by that category.
- A Classroom object checksum match may deduplicate bytes but never merge authorization scopes.
- A Matrix room mapping cannot authorize membership; platform group policy and reconciliation do.
- A ChatGPT submission can enter only a draft/quarantine state.
- An archive cannot centrally include Matrix plaintext or private keys.
