# BLACK MAMBA

Protect the innocent. Expose the guilty. Never become what we fight.

A non-profit, multi-tenant evidence management platform for investigating online scams and
fraud. Teams collect, preserve, verify and report evidence; every action is recorded in a
tamper-evident audit log. See [CLAUDE.md](CLAUDE.md) for the hard rules,
[docs/SRS.md](docs/SRS.md) for requirements, [docs/SYSTEM_ARCHITECTURE.md](docs/SYSTEM_ARCHITECTURE.md)
for the design and [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md) to run it in production.

## What it does

- **Organisations (SaaS):** teams apply, a platform admin vets them, admins invite members.
  Data is isolated per organisation. Roles: investigator, reviewer, org admin, platform admin.
- **Accounts:** argon2 passwords, TOTP 2FA (mandatory for admins), invitation and reset links,
  login rate limiting, instant token revocation.
- **Cases:** `open → investigating → review → closed`; closed cases are read-only until a
  reviewer reopens them.
- **Evidence:** files, screenshots, URLs and written observations. SHA-256 at capture,
  write-once encrypted storage, re-hashed on every download, never edited or deleted (only
  excluded with a reason, also enforced by database triggers).
- **Web archiving:** a sandboxed headless browser captures a full-page screenshot, the HTML,
  the final URL, the HTTP status and a UTC timestamp. SSRF-protected.
- **Findings and review:** claims must cite evidence; only a reviewer who is not the author
  can verify one (enforced server side).
- **PDF reports:** only verified findings, evidence hashes, chain of custody and audit-chain
  status. Each report is itself hashed and stored as evidence.
- **ARCHIVIST agent:** drafts a summary and timeline (Claude, Ollama or offline). Always
  labelled "AI draft — not verified"; it can never create findings or reach a report.

## Stack

FastAPI · SQLAlchemy 2 (async) · PostgreSQL 16 · Redis + RQ · MinIO (SSE) · Playwright ·
WeasyPrint · LangGraph · Next.js 16 (App Router, Tailwind) · Docker Compose · Caddy

## Quick start (Docker)

Requirements: Docker with Compose v2 (Docker Desktop on Windows/macOS, or Docker Engine on Linux/WSL2).

```bash
cp .env.example .env          # then replace every change-me value (commands are in the file)
docker compose up -d --build --wait
```

The first build compiles MinIO from source and downloads Chromium; allow about 10 minutes.

| Service | URL |
|---|---|
| Web app | http://localhost:3000 |
| API docs (dev only) | http://localhost:8000/docs |
| MinIO console | http://localhost:9001 (`MINIO_ROOT_USER` / `MINIO_ROOT_PASSWORD`) |
| PostgreSQL | `localhost:${POSTGRES_HOST_PORT:-5432}` |

All ports bind to `127.0.0.1`. `minio-init` runs once (bucket, encryption, no public access)
and exits; that is expected. If another PostgreSQL already uses port 5432, set
`POSTGRES_HOST_PORT=5433` in `.env` and use that port in `DATABASE_URL`.

### Demo data (development only)

```bash
docker compose exec -e BM_SEED_PASSWORD='choose-a-long-password' api blackmamba seed-demo
```

This creates the org *Demo Investigations* with `lead@`, `reviewer@`, `admin@` and
`platform@demo.example.org`. The admin accounts need the TOTP secret the command prints:
add it to an authenticator app.

### Real accounts

```bash
docker compose exec api blackmamba create-platform-admin --email you@example.org --name "You"
docker compose exec api blackmamba create-org --name "My Team" --admin-email lead@example.org
```

## Setup on Windows (WSL2)

1. PowerShell as Administrator: `wsl --install -d Ubuntu-24.04`, reboot, create your Linux user.
2. Install [Docker Desktop](https://www.docker.com/products/docker-desktop/) and enable
   *Settings → Resources → WSL Integration → Ubuntu-24.04*.
3. In Ubuntu: `curl -LsSf https://astral.sh/uv/install.sh | sh`, then install Node 22 and
   pnpm (`corepack enable`).
4. Clone the repo inside the Linux filesystem (`~/black-mamba`, not `/mnt/c/...`): bind
   mounts and file watching are much faster there.

## Development

### Backend (`apps/api`)

```bash
cd apps/api
uv sync
uv run pytest                     # needs PostgreSQL: the compose `postgres` service is fine
uv run ruff check . && uv run ruff format --check . && uv run mypy
uv run bandit -q -r src -c pyproject.toml
uv run alembic upgrade head
uv run alembic revision --autogenerate -m "describe change"
uv run uvicorn blackmamba.main:app --reload
uv run python scripts/export_openapi.py openapi.json   # after API changes (CI checks it)
```

Tests use `TEST_DATABASE_URL` (or `DATABASE_URL`) and refuse any database whose name does not
end in `_test`: they drop and rebuild its schema. The compose Postgres creates
`blackmamba_test` automatically, so with the stack running:

```bash
TEST_DATABASE_URL=postgresql+asyncpg://blackmamba:<POSTGRES_PASSWORD>@localhost:<POSTGRES_HOST_PORT>/blackmamba_test uv run pytest
```

Without a reachable database, DB tests are skipped (CI sets `REQUIRE_DB=1` so they fail
instead). PDF tests need Pango (`apt install libpango-1.0-0 libpangoft2-1.0-0`), and archiver
browser tests need `uv run playwright install chromium`; otherwise they are skipped.

### Frontend (`apps/web`)

```bash
cd apps/web
pnpm install
API_URL=http://localhost:8000 pnpm dev   # http://localhost:3000
pnpm gen:api                             # regenerate the typed client from apps/api/openapi.json
pnpm typecheck && pnpm lint && pnpm build
E2E_PASSWORD='<seed password>' pnpm test:e2e   # against a running, seeded stack
```

### Operations

```bash
docker compose exec api blackmamba verify-all       # every audit chain + re-hash all evidence
docker compose exec api blackmamba verify-audit --org-id <uuid>
```

## CI/CD

`.github/workflows/ci.yml`:
- API: ruff, strict mypy, pytest with at least 80% coverage on PostgreSQL 16, migration drift, OpenAPI drift, Bandit, pip-audit.
- Web: typecheck, lint, build, pnpm audit.
- gitleaks secret scanning.
- A full docker compose + Playwright end-to-end run.

`.github/workflows/deploy.yml` deploys `main` to the VPS after CI passes and a human approves.
