"""FR-4: auto-archive job lifecycle and SSRF protection."""

import hashlib
import http.server
import shutil
import threading
from collections.abc import Iterator
from datetime import UTC, datetime
from pathlib import Path

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.core.config import get_settings
from blackmamba.core.db import get_sessionmaker
from blackmamba.models import ArchiveJobStatus, AuditLog, Evidence, Role, User
from blackmamba.services import url_safety
from blackmamba.services.storage import get_storage
from blackmamba.workers.archive import Capture, PlaywrightCapturer, process_archive_job
from tests.conftest import RecordingQueue
from tests.factories import auth, make_org, make_user


class FakeCapturer:
    def __init__(self, fail: Exception | None = None) -> None:
        self.fail = fail
        self.urls: list[str] = []

    async def capture(self, url: str) -> Capture:
        self.urls.append(url)
        if self.fail:
            raise self.fail
        return Capture(
            png=b"\x89PNG\r\n\x1a\nfake",
            html=b"<html><body>Earn $5000/week from home!</body></html>",
            final_url=url + "?redirected=1",
            http_status=200,
            captured_at=datetime(2026, 11, 9, 10, 0, tzinfo=UTC),
        )


@pytest.fixture
async def lead(session: AsyncSession) -> User:
    return await make_user(session, await make_org(session), Role.INVESTIGATOR)


async def _case_id(client: AsyncClient, user: User) -> str:
    response = await client.post(
        "/cases",
        headers=auth(user),
        json={"title": "Crypto doubling site", "category": "investment_scam"},
    )
    return str(response.json()["id"])


# ------------------------------------------------------------------ SSRF
@pytest.mark.parametrize(
    "url",
    [
        "file:///etc/passwd",
        "ftp://example.com/x",
        "javascript:alert(1)",
        "gopher://127.0.0.1:6379/_FLUSHALL",
        "http://localhost:8000/admin",
        "http://127.0.0.1/",
        "http://10.0.0.5/",
        "http://172.16.3.4/",
        "http://192.168.1.1/",
        "http://169.254.169.254/latest/meta-data/",
        "http://0.0.0.0/",
        "http://[::1]/",
        "http://[::ffff:127.0.0.1]/",
        "http://[fd00::1]/",
        "http://user:pass@example.com/",
        "http://redis.internal/",
        "http://100.64.0.1/",
    ],
)
async def test_archive_rejects_unsafe_urls(
    client: AsyncClient, lead: User, job_queue: RecordingQueue, url: str
) -> None:
    case_id = await _case_id(client, lead)

    response = await client.post(f"/cases/{case_id}/archive", headers=auth(lead), json={"url": url})

    assert response.status_code == 422, url
    assert job_queue.archive_jobs == []


async def test_hostname_resolving_to_private_ip_is_rejected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14", "10.1.2.3"]  # one public, one private: reject

    monkeypatch.setattr(url_safety, "resolve_host", fake_resolve)
    with pytest.raises(url_safety.UnsafeUrlError):
        await url_safety.ensure_public_url("https://evil-rebind.example/")


async def test_public_hostname_is_allowed(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    monkeypatch.setattr(url_safety, "resolve_host", fake_resolve)
    assert (
        await url_safety.ensure_public_url("https://scam.example/offer")
        == "https://scam.example/offer"
    )


# ------------------------------------------------------------------ lifecycle
async def test_archive_job_lifecycle(
    client: AsyncClient,
    lead: User,
    job_queue: RecordingQueue,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    monkeypatch.setattr(url_safety, "resolve_host", fake_resolve)
    case_id = await _case_id(client, lead)

    requested = await client.post(
        f"/cases/{case_id}/archive", headers=auth(lead), json={"url": "https://scam.example/offer"}
    )
    assert requested.status_code == 202, requested.text
    job = requested.json()
    assert job["status"] == "queued"
    assert [str(j) for j in job_queue.archive_jobs] == [job["id"]]

    capturer = FakeCapturer()
    status = await process_archive_job(
        job_queue.archive_jobs[0],
        sessionmaker=get_sessionmaker(),
        storage=get_storage(),
        capturer=capturer,
        settings=get_settings(),
    )
    assert status == ArchiveJobStatus.DONE

    done = (await client.get(f"/archive-jobs/{job['id']}", headers=auth(lead))).json()
    assert done["status"] == "done"
    assert done["started_at"] and done["finished_at"]
    assert len(done["evidence_ids"]) == 2
    evidence = (await session.scalars(select(Evidence).where(Evidence.case_id == case_id))).all()
    by_type = {e.type.value: e for e in evidence}
    assert set(by_type) == {"screenshot", "file"}
    assert by_type["screenshot"].sha256 == hashlib.sha256(b"\x89PNG\r\n\x1a\nfake").hexdigest()
    assert by_type["file"].mime == "text/html"
    for e in evidence:
        assert e.final_url == "https://scam.example/offer?redirected=1"
        assert e.http_status == 200
        assert e.captured_by == lead.id
        assert e.captured_at == datetime(2026, 11, 9, 10, 0, tzinfo=UTC)
    verify = await client.get(f"/evidence/{by_type['screenshot'].id}/verify", headers=auth(lead))
    assert verify.json()["match"] is True

    # Re-running a finished job (e.g. an RQ retry) does not capture twice.
    again = await process_archive_job(
        job_queue.archive_jobs[0],
        sessionmaker=get_sessionmaker(),
        storage=get_storage(),
        capturer=capturer,
        settings=get_settings(),
    )
    assert again == ArchiveJobStatus.DONE
    assert len(capturer.urls) == 1


async def test_archive_job_failure_is_recorded(
    client: AsyncClient,
    lead: User,
    job_queue: RecordingQueue,
    session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def fake_resolve(host: str, port: int) -> list[str]:
        return ["93.184.215.14"]

    monkeypatch.setattr(url_safety, "resolve_host", fake_resolve)
    case_id = await _case_id(client, lead)
    job = (
        await client.post(
            f"/cases/{case_id}/archive", headers=auth(lead), json={"url": "https://down.example/"}
        )
    ).json()

    status = await process_archive_job(
        job_queue.archive_jobs[0],
        sessionmaker=get_sessionmaker(),
        storage=get_storage(),
        capturer=FakeCapturer(fail=TimeoutError("navigation timeout")),
        settings=get_settings(),
    )

    assert status == ArchiveJobStatus.FAILED
    failed = (await client.get(f"/archive-jobs/{job['id']}", headers=auth(lead))).json()
    assert failed["status"] == "failed"
    assert "navigation timeout" in failed["error"]
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "archive.failed" in actions


# ------------------------------------------------------------------ real browser
def _chromium_installed() -> bool:
    candidates = [
        Path.home() / "AppData/Local/ms-playwright",
        Path.home() / ".cache/ms-playwright",
    ]
    return any(p.exists() and any(p.glob("chromium-*")) for p in candidates) or bool(
        shutil.which("chromium")
    )


@pytest.fixture
def local_site() -> Iterator[str]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            if self.path == "/start":
                self.send_response(302)
                self.send_header("Location", "/offer")
                self.end_headers()
                return
            body = b"<html><head><title>Offer</title></head><body><h1>Guaranteed 300% returns</h1></body></html>"
            self.send_response(200)
            self.send_header("Content-Type", "text/html")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, *args: object) -> None:
            pass

    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()


@pytest.mark.skipif(not _chromium_installed(), reason="Playwright Chromium not installed")
async def test_playwright_captures_local_page(local_site: str) -> None:
    settings = get_settings().model_copy(update={"archive_allow_private_hosts": True})

    capture = await PlaywrightCapturer(settings).capture(f"{local_site}/start")

    assert capture.png.startswith(b"\x89PNG")
    assert b"Guaranteed 300% returns" in capture.html
    assert capture.final_url == f"{local_site}/offer"
    assert capture.http_status == 200


@pytest.mark.skipif(not _chromium_installed(), reason="Playwright Chromium not installed")
async def test_playwright_guard_blocks_private_hosts(local_site: str) -> None:
    capture_settings = get_settings().model_copy(update={"archive_allow_private_hosts": False})

    with pytest.raises(Exception, match="ERR_BLOCKED_BY_CLIENT"):
        await PlaywrightCapturer(capture_settings).capture(f"{local_site}/start")
