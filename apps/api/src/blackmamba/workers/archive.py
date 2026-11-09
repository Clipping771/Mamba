"""Auto-archive worker (FR-4).

Opens a public URL in sandboxed headless Chromium and captures a full-page PNG, the rendered
HTML, the final URL after redirects, the HTTP status and a UTC timestamp. Passive only: no
login, no form submission, no clicking, no downloads. Every network request the page makes
is re-checked against the SSRF guard.

RQ entrypoint: `run_archive_job(job_id)`; the async core is `process_archive_job`.
"""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from blackmamba.core.config import Settings, get_settings
from blackmamba.core.db import get_engine, get_sessionmaker
from blackmamba.models import ArchiveJob, ArchiveJobStatus, Case, EvidenceType
from blackmamba.services import audit
from blackmamba.services.evidence import store_content
from blackmamba.services.storage import ObjectStorage, get_storage
from blackmamba.services.url_safety import UnsafeUrlError, ensure_public_url

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/130.0 Safari/537.36 BlackMambaArchiver/0.1"
)
MAX_PNG_BYTES = 40 * 1024 * 1024


@dataclass(frozen=True)
class Capture:
    png: bytes
    html: bytes
    final_url: str
    http_status: int | None
    captured_at: datetime


class Capturer(Protocol):
    async def capture(self, url: str) -> Capture: ...


class PlaywrightCapturer:
    def __init__(self, settings: Settings) -> None:
        self.timeout_ms = settings.archive_timeout_seconds * 1000
        self.allow_private = settings.archive_allow_private_hosts

    async def capture(self, url: str) -> Capture:
        from playwright.async_api import Route, async_playwright  # heavy import: worker only

        allow_private = self.allow_private
        checked: dict[str, bool] = {}

        async def guard(route: Route) -> None:
            request_url = route.request.url
            if request_url.startswith(("data:", "blob:")):
                await route.continue_()
                return
            origin = request_url.split("/", 3)[:3]
            key = "/".join(origin)
            if key not in checked:
                try:
                    await ensure_public_url(request_url, allow_private=allow_private)
                    checked[key] = True
                except UnsafeUrlError:
                    checked[key] = False
            if checked[key]:
                await route.continue_()
            else:
                log.warning("archiver blocked request to %s", key)
                await route.abort("blockedbyclient")

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(
                headless=True,
                args=["--disable-dev-shm-usage", "--no-first-run", "--disable-extensions"],
            )
            try:
                context = await browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    user_agent=USER_AGENT,
                    viewport={"width": 1366, "height": 900},
                    java_script_enabled=True,
                    bypass_csp=False,
                )
                await context.route("**/*", guard)
                page = await context.new_page()
                # No pop-ups: close any window the site tries to open.
                page.on("popup", lambda popup: asyncio.ensure_future(popup.close()))
                response = await page.goto(url, wait_until="load", timeout=self.timeout_ms)
                try:
                    await page.wait_for_load_state("networkidle", timeout=5000)
                except Exception:
                    log.debug("network did not go idle for %s", url)
                captured_at = datetime.now(UTC)
                png = await page.screenshot(full_page=True, type="png", timeout=self.timeout_ms)
                html = (await page.content()).encode("utf-8")
                final_url = page.url
                status = response.status if response is not None else None
            finally:
                await browser.close()
        if len(png) > MAX_PNG_BYTES:
            raise RuntimeError("screenshot exceeds size limit")
        return Capture(
            png=png, html=html, final_url=final_url, http_status=status, captured_at=captured_at
        )


async def process_archive_job(
    job_id: uuid.UUID,
    *,
    sessionmaker: async_sessionmaker[AsyncSession],
    storage: ObjectStorage,
    capturer: Capturer,
    settings: Settings,
) -> ArchiveJobStatus:
    async with sessionmaker() as session:
        job = await session.get(ArchiveJob, job_id)
        if job is None:
            log.error("archive job %s not found", job_id)
            return ArchiveJobStatus.FAILED
        if job.status != ArchiveJobStatus.QUEUED:
            return job.status  # idempotent: RQ retries must not capture twice
        case = await session.get(Case, job.case_id)
        if case is None:
            return ArchiveJobStatus.FAILED
        org_id = case.org_id
        active: ArchiveJob = job  # narrowed, for use in the closure below
        job.status = ArchiveJobStatus.RUNNING
        job.started_at = datetime.now(UTC)
        await session.commit()

        try:
            url = await ensure_public_url(
                job.url, allow_private=settings.archive_allow_private_hosts
            )
            capture = await asyncio.wait_for(
                capturer.capture(url), timeout=settings.archive_timeout_seconds + 30
            )
            if not capture.final_url.startswith(("http://", "https://")):
                raise UnsafeUrlError("navigation ended on a non-http(s) URL")

            async def save(kind: EvidenceType, data: bytes, mime: str, ext: str) -> uuid.UUID:
                evidence = await store_content(
                    session,
                    storage,
                    case=case,
                    actor=None,
                    captured_by=active.created_by,
                    type=kind,
                    data=data,
                    mime=mime,
                    title=f"{'Screenshot' if ext == 'png' else 'HTML'} of {active.url}"[:300],
                    original_filename=f"archive-{active.id}.{ext}",
                    source_url=active.url,
                    final_url=capture.final_url,
                    http_status=capture.http_status,
                    archive_job_id=active.id,
                    captured_at=capture.captured_at,
                )
                return evidence.id

            evidence_ids = [
                await save(EvidenceType.SCREENSHOT, capture.png, "image/png", "png"),
                await save(EvidenceType.FILE, capture.html, "text/html", "html"),
            ]
            job.status = ArchiveJobStatus.DONE
            job.finished_at = datetime.now(UTC)
            await audit.record(
                session,
                org_id=org_id,
                actor_id=job.created_by,
                action="archive.done",
                target_type="archive_job",
                target_id=job.id,
                payload={
                    "case_id": str(case.id),
                    "url": job.url,
                    "final_url": capture.final_url,
                    "http_status": capture.http_status,
                    "evidence_ids": [str(e) for e in evidence_ids],
                },
            )
            await session.commit()
            return ArchiveJobStatus.DONE
        except Exception as exc:
            await session.rollback()
            log.warning("archive job %s failed: %s", job_id, exc)
            job = await session.get(ArchiveJob, job_id)
            if job is None:  # deleted meanwhile; nothing to record
                return ArchiveJobStatus.FAILED
            job.status = ArchiveJobStatus.FAILED
            job.finished_at = datetime.now(UTC)
            job.error = (str(exc) or type(exc).__name__)[:1000]
            await audit.record(
                session,
                org_id=org_id,
                actor_id=job.created_by,
                action="archive.failed",
                target_type="archive_job",
                target_id=job.id,
                payload={"case_id": str(job.case_id), "url": job.url, "error": job.error},
            )
            await session.commit()
            return ArchiveJobStatus.FAILED


async def _run(job_id: uuid.UUID) -> ArchiveJobStatus:
    settings = get_settings()
    try:
        return await process_archive_job(
            job_id,
            sessionmaker=get_sessionmaker(),
            storage=get_storage(),
            capturer=PlaywrightCapturer(settings),
            settings=settings,
        )
    finally:
        await get_engine().dispose()
        get_sessionmaker.cache_clear()
        get_engine.cache_clear()


def run_archive_job(job_id: str) -> str:
    """RQ entrypoint (sync)."""
    return asyncio.run(_run(uuid.UUID(job_id))).value
