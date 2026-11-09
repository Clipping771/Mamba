# Claude Code Sprint Prompts

How to use: open the `black-mamba` folder in WSL, run `claude`, then paste one sprint prompt at a time. Finish and test each sprint before the next. After each sprint: review the diff, run tests, commit.

---

## Sprint 1 — Foundation
```
Read CLAUDE.md, docs/SRS.md and docs/SYSTEM_ARCHITECTURE.md first.
Sprint 1: create the foundation.
- docker-compose.yml with postgres:16, redis:7, minio (with console), api, worker (placeholders ok).
- apps/api: uv project (Python 3.12), FastAPI app with /health, config via pydantic-settings, SQLAlchemy 2 async engine, Alembic configured, ruff + mypy + pytest set up.
- .env.example, .gitignore, README with setup steps for WSL2.
- GitHub Actions CI: ruff, mypy, pytest (with a postgres service).
- One test for /health.
Make `docker compose up -d` start everything and `uv run pytest` pass. Show me the commands to verify.
```

## Sprint 2 — Auth & RBAC (FR-1)
```
Sprint 2: implement FR-1 from docs/SRS.md.
- users table + Alembic migration; argon2 password hashing.
- /auth/login, /auth/refresh, /auth/me; JWT access + refresh.
- TOTP 2FA enable/verify; admins must have 2FA.
- Role dependency (investigator, reviewer, admin); admin user CRUD.
- Login rate limiting.
- Create a CLI command to bootstrap the first admin.
- Implement the audit service now (FR-9): append-only audit_log with hash chain + verify_chain(); log every write.
Tests: 401/403 cases, 2FA, audit chain tamper detection.
```

## Sprint 3 — Cases & Evidence (FR-2, FR-3, FR-5)
```
Sprint 3: implement FR-2, FR-3, FR-5.
- cases with status transitions (reject invalid with 409).
- evidence: upload file/screenshot, add url/note; store in MinIO with random key and SSE; compute SHA-256, size, mime, captured_at UTC, captured_by.
- No update/delete for evidence; only mark excluded with reason.
- GET /evidence/{id}/verify recomputes hash.
- Audit every write.
Tests: transitions, immutability, tamper detection via verify endpoint.
```

## Sprint 4 — Auto-archive worker (FR-4)
```
Sprint 4: implement FR-4.
- archive_jobs table; POST /cases/{id}/archive {url} enqueues an RQ job.
- Worker container with Playwright Chromium: open the public URL, no login, no form submission, no clicking; capture full-page PNG, HTML, final URL, HTTP status, UTC timestamp; timeout 60s.
- Save artefacts as evidence (with hashes) linked to the case; update job status.
- Reject non-http(s) URLs and private/internal IP ranges (SSRF protection).
Tests: job lifecycle with a local test page, SSRF rejection.
```

## Sprint 5 — Dashboard (Next.js)
```
Sprint 5: build apps/web with Next.js App Router, TypeScript, Tailwind, pnpm.
Pages: Login (with 2FA step), Case list (filter by status/category), Case detail (evidence timeline, findings, archive-URL form with job status), Add evidence, Admin users.
Typed API client generated from FastAPI OpenAPI. Dark, clean, professional UI. Add web to docker-compose.
```

## Sprint 6 — Findings & Review (FR-6, FR-7)
```
Sprint 6: implement FR-6 and FR-7.
- findings + finding_evidence; finding requires ≥1 evidence (422 otherwise).
- draft → in_review → verified|rejected; only reviewer, reviewer ≠ author (enforced in backend), rejection needs reason.
- Review queue page in the web app.
Tests: self-approval blocked, evidence requirement, role checks.
```

## Sprint 7 — PDF Report (FR-8)
```
Sprint 7: implement FR-8 with WeasyPrint.
Report: case summary, verified findings only, evidence table with SHA-256 and capture times, chain-of-custody table, generation timestamp, "Prepared under the BLACK MAMBA Code" footer.
Store the PDF in MinIO, hash it, save as evidence type 'report'. Add Report preview page.
Tests: report never includes draft/rejected findings or AI drafts.
```

## Sprint 8 — ARCHIVIST agent (FR-10)
```
Sprint 8: implement FR-10.
- apps/api agents/archivist.py using LangGraph; LLM provider configurable via env (hosted API or Ollama).
- Input: case evidence metadata + notes. Output: summary + chronological timeline.
- Save as note with is_ai_draft=true, shown in UI with "AI draft — not verified" badge.
- Agent has no permission to create/verify findings; it cannot fetch URLs itself.
Tests: mock LLM; ensure output is labelled and excluded from reports.
```

---

## After Sprint 8 — Testing & Deployment
```
Run the full test plan: unit, integration, Playwright e2e (login → case → evidence → finding → review → PDF), bandit, pip-audit, gitleaks. Target 80%+ backend coverage. Fix all critical/high issues.
Then write docs/DEPLOYMENT.md for a single VPS: Caddy HTTPS, production .env, firewall (443 only), daily encrypted offsite backup of Postgres + MinIO, restore test, GitHub Actions deploy on main, uptime/error monitoring. Invite-only access.
```
