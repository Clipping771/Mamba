# BLACK MAMBA — System Architecture

```
 Browser ──HTTPS──▶ Caddy (TLS, 443 only)
                      │
                      ▼
 Next.js dashboard + BFF (/api/auth, /api/bm/*)      httpOnly session cookies, CSRF header
                      │ Bearer JWT (internal network)
                      ▼
 FastAPI ── Auth / RBAC / tenancy ── Audit service (hash chain per organisation)
   │   │      │
   │   │      └── ARCHIVIST agent (LangGraph) ──▶ LLM provider (Claude API | Ollama | fake)
   │   └── Redis queue ──▶ RQ worker ──▶ Playwright Chromium (SSRF-guarded) ──▶ public web
   │
 PostgreSQL 16 (orgs, users, cases, evidence, findings, notes, archive_jobs, audit_log)
 MinIO (evidence objects, write-once keys, SSE-S3)
```

Decisions: [ADR-001](adr/ADR-001-tech-stack.md) stack ·
[ADR-002](adr/ADR-002-saas-multi-tenancy.md) multi-tenancy and roles ·
[ADR-003](adr/ADR-003-web-auth-and-infrastructure.md) web sessions, MinIO, archiver isolation.

## Data model
| Table | Key fields |
|---|---|
| organizations | id, name, slug, status (pending/active/suspended/rejected), contact_name, contact_email, purpose |
| users | id (uuid), org_id (NULL for platform admins), name, email (unique, lower-case), password_hash (argon2), role, totp_secret (Fernet-encrypted), totp_enabled, is_active, token_version, last_login_at |
| one_time_tokens | id, purpose (invite/password_reset), token_hash (sha256), email, org_id, role, user_id, expires_at, used_at |
| cases | id, org_id, title, category, description, status, lead_id → users, created_at, updated_at |
| evidence | id, case_id, type (url/file/screenshot/note/report), title, description, source_url, final_url, http_status, storage_key, sha256, size, mime, original_filename, captured_at, captured_by, archive_job_id, excluded, excluded_reason/at/by |
| archive_jobs | id, case_id, url, status, error, created_by, created_at, started_at, finished_at (evidence links via evidence.archive_job_id) |
| findings | id, case_id, claim, status, author_id, reviewer_id, review_note, created_at, submitted_at, reviewed_at |
| finding_evidence | finding_id, evidence_id (PK pair) |
| notes | id, case_id, body, is_ai_draft, ai_model, author_id, created_at |
| audit_log | id (bigserial), org_id, actor_id, action, target_type, target_id, payload (jsonb), ts, prev_hash, hash |

### Database-level integrity (migration `a1b2c3d4e5f6`)
- `audit_log`: UPDATE, DELETE and TRUNCATE are rejected by triggers.
- `notes`: append-only.
- `evidence`: DELETE rejected; UPDATE allowed only for the exclusion columns, and only once.
- `findings` / `finding_evidence`: frozen once a finding is verified.

## Key flows
1. **Archive URL:** POST /cases/{id}/archive → SSRF check → job queued → worker opens URL in
   headless Chromium (no login, no form submission, no clicks; every request re-checked) →
   PNG + HTML → MinIO (SSE) → hashes → evidence rows + audit entry, all in one transaction.
2. **Finding review:** investigator creates a finding citing ≥1 evidence item → submits →
   a reviewer who is not the author verifies or rejects (with reason) → audit.
3. **Report:** reviewer requests PDF → only verified findings, evidence table with hashes,
   chain-of-custody from the audit log, audit-chain status → WeasyPrint → hashed → stored as
   evidence `report`. Refused if the audit chain fails verification.
4. **ARCHIVIST:** case metadata + evidence metadata + human notes (never file contents, never
   earlier AI drafts) → LangGraph (summarize → timeline → compose) → note with
   `is_ai_draft=true`, labelled "AI draft — not verified". No tools, no network, no DB access.

## Security
- Audit hash: `sha256(prev_hash || canonical_json({org_id, actor_id, action, target_type,
  target_id, payload, ts}))`; genesis prev_hash = 64 zeros; one chain per organisation,
  serialised with a transaction-scoped advisory lock.
- Evidence is hashed at capture and re-hashed on every download and verify; mismatches are
  refused and audited. Downloads are always attachments with a `sandbox` CSP.
- Login: argon2, timing-equalised unknown users, rate limited per IP and per IP+email
  (Redis), TOTP for 2FA (mandatory for admins), token_version revocation.
- The worker has outbound HTTP only and no published ports. Data services have no internet
  access in production. See ADR-003 for the remaining least-privilege step.
