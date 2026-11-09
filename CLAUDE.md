# BLACK MAMBA — Project Instructions for Claude Code

## Mission
Protect the innocent. Expose the guilty. Never become what we fight.

BLACK MAMBA is a non-profit investigation and victim-protection platform. Investigators use it to collect, preserve, verify and report evidence of online scams and fraud. It is an **evidence management system**, not an offensive tool.

## Hard rules (never break these)
1. **No offensive capability.** Do not write code that scans, probes, exploits, brute-forces or accesses systems without authorisation. Archiving a public web page by URL (Playwright screenshot + HTML) is allowed.
2. **No doxxing features.** Do not build features that collect personal data about private individuals (home address, family, phone lookup, etc.). Investigations focus on scam infrastructure: domains, websites, payment pages, ads, messages.
3. **AI never decides guilt.** AI output is always labelled `AI draft — not verified` and can never set a finding to `verified`. Only a human reviewer can.
4. **Author ≠ reviewer.** A user may never approve their own finding. Enforce this in the backend, not only in the UI.
5. **Reports include only verified findings.**
6. **Evidence is immutable.** Evidence files are never edited or overwritten. Store SHA-256 at capture; verify on read.
7. **Audit log is append-only** and hash-chained (`hash = sha256(prev_hash + canonical_json(entry))`). No update/delete endpoints. Add a verify-chain function and test.
8. **Secrets** live only in `.env` (gitignored). Provide `.env.example`.
9. **Victim data** is minimised, encrypted and access-restricted.

## Stack
- Backend: Python 3.12, FastAPI, SQLAlchemy 2.x, Alembic, Pydantic v2, managed with **uv**
- DB: PostgreSQL 16
- Files: MinIO (S3-compatible), server-side encryption
- Queue: Redis + RQ
- Archiver: Playwright (Chromium)
- Frontend: Next.js (App Router), TypeScript, Tailwind, managed with **pnpm**
- AI: LangGraph + hosted LLM API (configurable) / Ollama
- PDF: WeasyPrint
- Dev: Docker Compose on WSL2. CI: GitHub Actions

## Repository layout
```
black-mamba/
├── apps/
│   ├── api/        # FastAPI (src/blackmamba/...), tests/, alembic/
│   └── web/        # Next.js
├── infrastructure/docker/
├── docs/           # SRS.md, SYSTEM_ARCHITECTURE.md, adr/
├── docker-compose.yml
├── .env.example
└── CLAUDE.md
```

## Backend structure (apps/api/src/blackmamba)
`core/` (config, security, db) · `models/` · `schemas/` · `api/routes/` · `services/` (evidence, audit, report) · `workers/` · `agents/`

## Conventions
- Python: ruff + mypy (strict where practical), pytest. TypeScript: eslint + tsc --noEmit.
- Every endpoint: auth required (except login/health), role check, audit log entry for writes.
- Every feature ships with tests. Keep CI green.
- Small PR-sized changes; trunk-based (`main` + `feature/*`).
- Record significant decisions as ADRs in `docs/adr/`.
- Read `docs/SRS.md` for requirements (FR-1…FR-10, NFR-1…NFR-6) and reference them in commits.

## Commands (keep up to date)
- `docker compose up -d --build --wait` — start Postgres, Redis, MinIO, api, worker, web (web: http://localhost:3000)
- `docker compose exec -e BM_SEED_PASSWORD=... api blackmamba seed-demo` — dev demo org + one user per role
- `docker compose exec api blackmamba verify-all` — verify every audit chain and re-hash all evidence
- `cd apps/api && uv run pytest` — backend tests (needs PostgreSQL; DB name must end in `_test`, see README)
- `cd apps/api && uv run ruff check . && uv run mypy && uv run bandit -q -r src -c pyproject.toml`
- `cd apps/api && uv run alembic upgrade head` — migrations
- `cd apps/api && uv run python scripts/export_openapi.py openapi.json` then `cd apps/web && pnpm gen:api` — after API changes
- `cd apps/web && pnpm dev` / `pnpm typecheck && pnpm lint` / `E2E_PASSWORD=... pnpm test:e2e`
- Production: see `docs/DEPLOYMENT.md` (`docker-compose.prod.yml`, Caddy, backups, restore test)

## Multi-tenancy (ADR-002)
Every case belongs to an organisation. Always scope queries by the caller's `org_id` (use
`services.cases.get_case`, `get_evidence`, `get_finding`); out-of-org access returns 404.
Audit entries carry `org_id` and case-related ones include `payload.case_id`.
