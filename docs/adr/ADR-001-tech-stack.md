# ADR-001: Technology stack

- Status: Accepted
- Date: 2026-11-09

## Context
Solo founder building with Claude Code on Windows/WSL2, free budget, needs strong evidence integrity and a path to multi-agent AI.

## Decision
Modular monolith: FastAPI + PostgreSQL + MinIO + Redis/RQ + Playwright; Next.js frontend; LangGraph for agents; Docker Compose for dev and first production.

## Consequences
+ One deployable backend, simple ops, Python ecosystem for AI and OSINT tooling.
+ S3-compatible storage lets us move to a cloud provider later without code changes.
− Two languages (Python, TypeScript). Accepted for best-in-class tooling on each side.
− No Kubernetes; revisit if load requires (new ADR).
