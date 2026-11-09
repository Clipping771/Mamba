# BLACK MAMBA — Software Requirements Specification (v1.0)

## 1. Purpose
A non-profit platform for collecting, preserving, verifying and reporting evidence of online scams and fraud, and supporting victims. Scope of this SRS: MVP (v0.1).

## 2. Users and roles
BLACK MAMBA is multi-tenant (ADR-002): every user except the platform operator belongs to one
organisation, and all data is scoped to it.

| Role | Permissions |
|---|---|
| investigator | Read all cases in the org; create cases; edit cases they lead; add evidence and findings to them |
| reviewer | Everything investigator can, on every case in the org + approve/reject findings written by others; reopen closed cases |
| admin | Organisation admin: invite and manage users and roles; read and verify the org audit log; no case access |
| platform_admin | Operator: approve, reject, suspend organisations; verify audit chains; no case access |
| victim (v0.3) | Submit a report via secure intake form |

## 3. Functional requirements and acceptance criteria

**FR-1 Authentication & RBAC**
- Users log in with email + password; password hashed with argon2.
- TOTP 2FA can be enabled; admins must have it.
- JWT access token (short-lived) + refresh token.
- AC: unauthenticated requests to protected routes return 401; wrong role returns 403.

**FR-2 Cases**
- Fields: title, category (e.g. job scam, investment scam, phishing, marketplace), description, status, lead.
- Status flow: `open → investigating → review → closed` (closed can be reopened by reviewer).
- AC: invalid transitions rejected with 409; every change audited.

**FR-3 Evidence**
- Types: `url`, `file`, `screenshot`, `note`.
- Files stored in MinIO under a random key; never overwritten.
- AC: evidence cannot be edited or deleted via API (only marked `excluded` with reason, audited).

**FR-4 Auto-archive**
- Given a URL, a background job captures: full-page PNG, raw HTML, final URL after redirects, HTTP status, timestamp (UTC).
- AC: job status visible (queued/running/done/failed); artefacts become evidence linked to the case.

**FR-5 Integrity metadata**
- On capture: SHA-256, size, mime type, captured_at (UTC), captured_by.
- `GET /evidence/{id}/verify` recomputes hash and returns match/mismatch.
- AC: tampered file in storage → mismatch.

**FR-6 Findings**
- A finding = a claim + ≥1 linked evidence item.
- Status: `draft → in_review → verified | rejected`.
- AC: creating/submitting a finding without evidence fails with 422.

**FR-7 Verification**
- Only reviewers may verify/reject; reviewer ≠ author; rejection requires a reason.
- AC: author attempting to verify own finding → 403 (backend-enforced).

**FR-8 PDF report**
- Generated per case; includes case summary, verified findings, evidence list with hashes and capture times, chain-of-custody table.
- Excludes draft/rejected findings and AI drafts.
- AC: report contains zero unverified findings; report file itself is hashed and stored as evidence-type `report`.

**FR-9 Audit log**
- Every write action recorded: actor, action, target type/id, timestamp, payload summary, prev_hash, hash.
- Append-only; `verify_chain()` detects any modification.
- AC: test modifies a row directly in DB → verify_chain fails.

**FR-10 ARCHIVIST agent**
- Input: a case's evidence metadata + notes. Output: summary and chronological timeline draft.
- Saved as a note labelled `AI draft — not verified`; cannot create or verify findings.
- AC: agent output never appears in reports unless a human rewrites it as a finding and it is verified.

**FR-11 Organisations & onboarding (SaaS)**
- Organisations apply publicly; a platform admin approves, rejects or suspends them.
- Approval issues a single-use admin invitation; org admins invite members by email/link.
- Invitation and password-reset tokens are single-use, expire, and are stored only as hashes.
- AC: a user never sees another organisation's cases, evidence or users (404); a suspended
  organisation's users cannot sign in or use existing tokens (403).

## 4. Non-functional requirements
- **NFR-1 Security:** HTTPS in prod; MinIO SSE; secrets in env; OWASP Top 10 addressed; rate-limit login.
- **NFR-2 Integrity:** immutable evidence; hash-chained audit log.
- **NFR-3 Privacy:** victim PII in separate table, field-level encryption, admin/lead-only access; data minimisation.
- **NFR-4 Reliability:** daily encrypted offsite backup; monthly restore test.
- **NFR-5 Usability:** new case + first evidence in under 5 minutes.
- **NFR-6 Legal/Methodology:** chain of custody aligned with the Berkeley Protocol on Digital Open Source Investigations; only publicly available information or material supplied with consent.

## 5. Out of scope (MVP)
13-agent system, public publishing of names, mobile app, any active scanning or testing of third-party systems, Kubernetes.
