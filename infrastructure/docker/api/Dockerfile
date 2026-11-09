# BLACK MAMBA API and archive-worker images. Build context: apps/api
#   --target api     FastAPI + WeasyPrint (PDF reports)
#   --target worker  RQ worker + Playwright Chromium (URL archiver)
FROM python:3.12-slim-bookworm AS base

COPY --from=ghcr.io/astral-sh/uv:0.11.16 /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/app/.venv

# WeasyPrint needs Pango; DejaVu fonts give the report predictable rendering.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 fonts-dejavu-core \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 10001 app

WORKDIR /app

# Dependencies first for layer caching.
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project

COPY . .
RUN uv sync --locked --no-dev && chown -R app:app /app

ENV PATH="/app/.venv/bin:$PATH"

# ------------------------------------------------------------------ api
FROM base AS api
USER app
EXPOSE 8000
# Proxy headers: the real client IP (for login rate limiting) comes from the web/Caddy hop.
CMD ["sh", "-c", "alembic upgrade head && exec uvicorn blackmamba.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips \"${FORWARDED_ALLOW_IPS:-127.0.0.1}\""]

# ------------------------------------------------------------------ worker
FROM base AS worker
ENV PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
RUN playwright install --with-deps chromium \
    && chmod -R a+rX /ms-playwright \
    && rm -rf /var/lib/apt/lists/*
USER app
CMD ["sh", "-c", "exec rq worker --url \"$REDIS_URL\" --with-scheduler archive"]
