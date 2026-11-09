# ADR-002: Multi-tenant SaaS with vetted, invite-only organisations

- Status: Accepted
- Date: 2026-11-09

## Context
BLACK MAMBA should serve several independent teams (non-profits, victim-support groups,
investigation units) from one deployment, without any of them seeing another's cases.
Abuse of the platform itself (stalking, harassment, doxxing) is a core risk, so access
must be vetted. There is no billing: it is free for approved organisations.

## Decision
- **Organisations are tenants.** Every case belongs to one organisation (`cases.org_id`);
  evidence, findings, notes and archive jobs hang off a case. Every query is scoped to the
  caller's organisation, and anything outside it returns 404 (not 403), so IDs reveal nothing.
- **One audit hash chain per organisation** (`audit_log.org_id`), plus a platform chain
  (`org_id IS NULL`) for operator actions. Each org can verify its own chain independently.
- **Roles**
  - `investigator`, `reviewer`: casework inside their org.
  - `admin` (organisation admin): users, invitations and the org audit log. No case access
    (separation of duties).
  - `platform_admin`: the operator. Vets organisations; no access to any org's cases.
  - Admin roles must have TOTP 2FA before any admin endpoint works.
- **Case access:** all casework users of an org can read its cases. Writing (evidence,
  notes, findings, archiving, edits) is for the case lead and reviewers. Closed cases are
  read-only until a reviewer reopens them.
- **Onboarding:** organisations apply at `/apply` → a platform admin approves → the contact
  gets a one-time admin invitation. Org admins invite members by email. Invitation and
  reset tokens are single-use, expire, and only their SHA-256 is stored.
- **Email is optional.** Without SMTP, the admin sees the link and shares it securely.

## Consequences
+ One deployment serves many teams; isolation is enforced in one place (`get_case` and
  org-scoped queries) and covered by tests.
+ Vetting plus invite-only access reduces the risk of the tool being misused.
− Isolation is enforced in the application, not by PostgreSQL row-level security. RLS is a
  possible future hardening step (new ADR).
− Platform admins can suspend an org but cannot read its data; support cases need the
  org admin's cooperation. This is intentional.
