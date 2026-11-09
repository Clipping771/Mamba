# ADR-003: Web session handling, MinIO from source, archiver isolation

- Status: Accepted
- Date: 2026-11-09

## 1. Backend-for-frontend sessions
**Decision.** The browser never holds JWTs. Next.js route handlers (`/api/auth/*`,
`/api/bm/*`) keep the access and refresh tokens in `httpOnly`, `Secure`, `SameSite=Strict`
cookies, attach the bearer token when proxying to FastAPI, and refresh it transparently.
Every state-changing request must carry the `x-bm-csrf: 1` header, which a cross-site form
cannot send. FastAPI is not exposed publicly; only Caddy → web is.

**Why.** An XSS bug cannot steal tokens, CSRF is blocked twice, and the API stays a pure
bearer-token API (CLI and tests use it directly).

## 2. MinIO built from pinned source
**Context.** MinIO stopped publishing community container images in late 2025; the old
Docker Hub and Quay images can no longer be pulled.

**Decision.** `infrastructure/docker/minio/Dockerfile` builds the `minio` server and `mc`
client from pinned release tags. The application only speaks the S3 API (with SSE-S3), so a
move to another S3-compatible store with server-side encryption needs configuration changes,
not code changes.

**Consequences.** First builds take several minutes. Bump `MINIO_RELEASE` / `MC_RELEASE`
deliberately and watch MinIO security advisories.

## 3. Archiver isolation
**Decision.** The worker container runs Chromium with no login, no clicks, no form
submission, no downloads, service workers blocked and pop-ups closed. Every network request
the page makes (redirects and sub-resources too) passes the same SSRF guard as the API: only
http(s) to hosts that resolve exclusively to public addresses. The worker is on the internal
data network plus an egress network, and exposes no ports.

**Trade-off.** The architecture document wanted the worker to have "no DB credentials beyond
its needs". It currently uses the application database user so it can record evidence and
audit entries in the same transaction. A dedicated least-privilege Postgres role (INSERT on
`evidence`/`audit_log`, UPDATE on `archive_jobs`) is the next hardening step.
