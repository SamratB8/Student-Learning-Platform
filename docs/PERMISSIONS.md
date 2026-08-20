# Permissions

## Evaluation rule

Authorize only when all are true:

1. The account state permits the action.
2. The principal has the required capability.
3. A valid grant covers the target scope.
4. The item's visibility/audience and relationship rules allow access.
5. Any extra rule (ownership, group membership, review state, Classroom access) passes.

The server evaluates this rule. UI visibility is convenience only.

## Roles

| Role | Purpose | Default scope |
|---|---|---|
| Visitor | Read explicitly public pages | Public only |
| Pending Applicant | Manage own application/status | Self |
| Member | Use approved member features | Assigned institution/branch and joined groups |
| Moderator | Review delegated community/content work | Explicit branch/subject/group scopes |
| Branch Admin | Manage branch academics and delegated moderators | One or more branches |
| Super Admin | Operate deployment and delegate access | Global |
| Draft Publisher | Submit untrusted drafts only | Draft ingress endpoint |

Roles are bundles, not hard-coded bypasses. Super Admin actions still require explicit policy, re-authentication where high risk, and audit.

## Capability catalogue

- Identity: `applications.read`, `users.approve`, `users.reject`, `users.suspend`, `users.disable`, `roles.grant`.
- Academics: `resources.read`, `resources.download`, `resources.create`, `resources.review`, `resources.publish`, `resources.delete`, `notes.curate`, `contributions.review`.
- Classroom: `classroom.connect.self`, `classroom.mapping.suggest`, `classroom.mapping.confirm`, `classroom.sync.operate`.
- Scheduling: `notices.create`, `notices.publish`, `routines.manage`, `events.manage`, `calendar.connect.self`, `meet.manage`.
- Community: `groups.create`, `groups.manage`, `groups.moderate`, `reports.review`.
- Administration: `configuration.manage`, `audit.read`, `integrations.manage`, `archives.create`, `archives.download`.
- Draft ingress: `drafts.submit` only.

## Scope types

- `GLOBAL`: entire deployment.
- `INSTITUTION:<id>`: one configured institution.
- `BRANCH:<id>`: one branch and its nested academic context.
- `SUBJECT:<id>`: one subject.
- `GROUP:<id>`: one platform group.
- `SELF`: the current user's own eligible data/actions.
- `PUBLIC`: explicitly published public information.

## Resource decisions

- Public visitor: only `PUBLIC` + published resources.
- Member view: `resources.read` plus matching audience/scope.
- Member download: both view permission and `resources.download`, plus the resource/version `can_download` rule.
- Moderator review does not grant publication unless `resources.publish` is separately delegated.
- Checksum deduplication does not make a branch-private resource visible in another branch.

## Messaging decisions

- Platform group membership controls eligibility for the mapped Matrix room.
- Moderators do not automatically join private rooms or gain decryption keys.
- A report reveals only evidence intentionally submitted under the reporting policy.
- Matrix administration credentials are service-only and confer no platform role.

## High-risk actions

Require re-authentication, confirmation, and audit for Super Admin changes, bulk role grants, user disabling, object deletion, integration credential rotation, Matrix-wide operations, archive generation/download, and retention-policy changes.

## Denial test matrix

Every protected endpoint must test at least: visitor, pending, wrong branch, right branch without capability, capability with wrong scope, suspended/disabled user, revoked grant, unpublished item, view-without-download, nonmember group, stale Classroom access, and forged provider/external ID.
