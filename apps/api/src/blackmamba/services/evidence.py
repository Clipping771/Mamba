"""Evidence capture and integrity (FR-3, FR-5).

Content is hashed (SHA-256) at capture, stored write-once under a random key with SSE, and
re-hashed on every read. Rows are immutable; exclusion is the only permitted change.
"""

import hashlib
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

import filetype
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.models import Case, Evidence, EvidenceType, User
from blackmamba.services import audit
from blackmamba.services.storage import ObjectStorage


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def detect_mime(data: bytes, declared: str | None) -> str:
    guessed = filetype.guess(data)
    if guessed is not None:
        return str(guessed.mime)
    if declared and "/" in declared and len(declared) < 200:
        return declared.split(";")[0].strip().lower()
    return "application/octet-stream"


async def store_content(
    session: AsyncSession,
    storage: ObjectStorage,
    *,
    case: Case,
    actor: User | None,
    captured_by: uuid.UUID,
    type: EvidenceType,
    data: bytes,
    mime: str,
    title: str = "",
    description: str = "",
    original_filename: str | None = None,
    source_url: str | None = None,
    final_url: str | None = None,
    http_status: int | None = None,
    archive_job_id: uuid.UUID | None = None,
    captured_at: datetime | None = None,
) -> Evidence:
    """Hash, store (write-once) and record one evidence item, plus its audit entry."""
    digest = sha256_hex(data)
    key = f"orgs/{case.org_id}/cases/{case.id}/{uuid.uuid4().hex}"
    await storage.put(key, data, mime)
    evidence = Evidence(
        case_id=case.id,
        type=type,
        title=title.strip(),
        description=description.strip(),
        source_url=source_url,
        final_url=final_url,
        http_status=http_status,
        storage_key=key,
        sha256=digest,
        size=len(data),
        mime=mime,
        original_filename=original_filename,
        captured_at=captured_at or datetime.now(UTC),
        captured_by=captured_by,
        archive_job_id=archive_job_id,
    )
    session.add(evidence)
    await session.flush()
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=actor.id if actor else captured_by,
        action="evidence.capture",
        target_type="evidence",
        target_id=evidence.id,
        payload={
            "case_id": str(case.id),
            "type": type.value,
            "sha256": digest,
            "size": len(data),
            "mime": mime,
            "source_url": source_url,
            "archive_job_id": str(archive_job_id) if archive_job_id else None,
        },
    )
    return evidence


async def add_url_reference(
    session: AsyncSession, *, case: Case, actor: User, url: str, title: str, description: str
) -> Evidence:
    """A URL recorded without capture (no content, so no hash). Use archiving to capture."""
    evidence = Evidence(
        case_id=case.id,
        type=EvidenceType.URL,
        title=title.strip(),
        description=description.strip(),
        source_url=url,
        captured_at=datetime.now(UTC),
        captured_by=actor.id,
    )
    session.add(evidence)
    await session.flush()
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=actor.id,
        action="evidence.capture",
        target_type="evidence",
        target_id=evidence.id,
        payload={"case_id": str(case.id), "type": EvidenceType.URL.value, "source_url": url},
    )
    return evidence


@dataclass(frozen=True)
class IntegrityResult:
    expected: str
    actual: str

    @property
    def match(self) -> bool:
        return self.expected == self.actual


async def read_and_verify(
    storage: ObjectStorage, evidence: Evidence
) -> tuple[bytes, IntegrityResult]:
    if evidence.storage_key is None or evidence.sha256 is None:
        raise ValueError("evidence has no stored content")
    data = await storage.get(evidence.storage_key)
    return data, IntegrityResult(expected=evidence.sha256, actual=sha256_hex(data))
