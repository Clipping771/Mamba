"""Evidence (FR-3) and integrity verification (FR-5). There is no update or delete endpoint:
evidence can only be marked excluded, with a reason."""

import uuid
from datetime import UTC, datetime
from typing import Annotated
from urllib.parse import quote

from fastapi import APIRouter, Depends, File, Form, Response, UploadFile, status
from sqlalchemy import select

from blackmamba.api.deps import (
    CaseworkUser,
    SessionDep,
    conflict,
    http_error,
    not_found,
    unprocessable,
)
from blackmamba.core.config import get_settings
from blackmamba.models import Case, Evidence, EvidenceType, User
from blackmamba.schemas.cases import (
    EvidenceOut,
    ExcludeRequest,
    NoteEvidenceCreate,
    UrlEvidenceCreate,
    VerifyOut,
)
from blackmamba.services import audit
from blackmamba.services import evidence as evidence_service
from blackmamba.services.cases import ensure_writable, get_case
from blackmamba.services.storage import ObjectMissingError, ObjectStorage, get_storage

router = APIRouter(tags=["evidence"])

StorageDep = Annotated[ObjectStorage, Depends(get_storage)]


async def get_evidence(
    session: SessionDep, user: User, evidence_id: uuid.UUID
) -> tuple[Evidence, Case]:
    row = (
        await session.execute(
            select(Evidence, Case)
            .join(Case, Case.id == Evidence.case_id)
            .where(Evidence.id == evidence_id, Case.org_id == user.org_id)
        )
    ).first()
    if row is None:
        raise not_found("evidence")
    return row


@router.get("/cases/{case_id}/evidence", response_model=list[EvidenceOut])
async def list_evidence(
    case_id: uuid.UUID, user: CaseworkUser, session: SessionDep, include_excluded: bool = True
) -> list[Evidence]:
    case = await get_case(session, user, case_id)
    query = select(Evidence).where(Evidence.case_id == case.id)
    if not include_excluded:
        query = query.where(Evidence.excluded.is_(False))
    return list(await session.scalars(query.order_by(Evidence.captured_at.desc())))


@router.post("/cases/{case_id}/evidence/file", response_model=EvidenceOut, status_code=201)
async def upload_evidence(
    case_id: uuid.UUID,
    user: CaseworkUser,
    session: SessionDep,
    storage: StorageDep,
    file: Annotated[UploadFile, File()],
    type: Annotated[EvidenceType, Form()] = EvidenceType.FILE,
    title: Annotated[str, Form(max_length=300)] = "",
    description: Annotated[str, Form(max_length=10000)] = "",
    source_url: Annotated[str | None, Form(max_length=4000)] = None,
) -> Evidence:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    if type not in {EvidenceType.FILE, EvidenceType.SCREENSHOT}:
        raise unprocessable("invalid_type", "uploads must be of type file or screenshot")
    if source_url and not source_url.startswith(("http://", "https://")):
        raise unprocessable("invalid_url", "source_url must be http(s)")
    max_bytes = get_settings().max_upload_mb * 1024 * 1024
    data = await file.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise http_error(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            "too_large",
            f"max {get_settings().max_upload_mb} MB",
        )
    if not data:
        raise unprocessable("empty_file", "the file is empty")
    evidence = await evidence_service.store_content(
        session,
        storage,
        case=case,
        actor=user,
        captured_by=user.id,
        type=type,
        data=data,
        mime=evidence_service.detect_mime(data, file.content_type),
        title=title or (file.filename or ""),
        description=description,
        original_filename=(file.filename or None),
        source_url=source_url,
    )
    await session.commit()
    return evidence


@router.post("/cases/{case_id}/evidence/url", response_model=EvidenceOut, status_code=201)
async def add_url_evidence(
    case_id: uuid.UUID, body: UrlEvidenceCreate, user: CaseworkUser, session: SessionDep
) -> Evidence:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    evidence = await evidence_service.add_url_reference(
        session,
        case=case,
        actor=user,
        url=str(body.url),
        title=body.title,
        description=body.description,
    )
    await session.commit()
    return evidence


@router.post("/cases/{case_id}/evidence/note", response_model=EvidenceOut, status_code=201)
async def add_note_evidence(
    case_id: uuid.UUID,
    body: NoteEvidenceCreate,
    user: CaseworkUser,
    session: SessionDep,
    storage: StorageDep,
) -> Evidence:
    """A written observation preserved as evidence (hashed like any other content)."""
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    evidence = await evidence_service.store_content(
        session,
        storage,
        case=case,
        actor=user,
        captured_by=user.id,
        type=EvidenceType.NOTE,
        data=body.body.encode("utf-8"),
        mime="text/plain; charset=utf-8",
        title=body.title,
    )
    await session.commit()
    return evidence


@router.get("/evidence/{evidence_id}", response_model=EvidenceOut)
async def read_evidence(
    evidence_id: uuid.UUID, user: CaseworkUser, session: SessionDep
) -> Evidence:
    evidence, _ = await get_evidence(session, user, evidence_id)
    return evidence


@router.get("/evidence/{evidence_id}/verify", response_model=VerifyOut)
async def verify_evidence(
    evidence_id: uuid.UUID, user: CaseworkUser, session: SessionDep, storage: StorageDep
) -> VerifyOut:
    """Recompute the SHA-256 of the stored object and compare it with the capture hash."""
    evidence, case = await get_evidence(session, user, evidence_id)
    if evidence.storage_key is None or evidence.sha256 is None:
        raise conflict("no_content", "this evidence item has no stored content to verify")
    try:
        _, result = await evidence_service.read_and_verify(storage, evidence)
        actual = result.actual
    except ObjectMissingError:
        actual = "missing"
    match = actual == evidence.sha256
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="evidence.verify" if match else "evidence.integrity_failure",
        target_type="evidence",
        target_id=evidence.id,
        payload={
            "case_id": str(case.id),
            "match": match,
            "expected": evidence.sha256,
            "actual": actual,
        },
    )
    await session.commit()
    return VerifyOut(
        evidence_id=evidence.id,
        expected=evidence.sha256,
        actual=actual,
        match=match,
        verified_at=datetime.now(UTC),
    )


@router.get("/evidence/{evidence_id}/content")
async def download_evidence(
    evidence_id: uuid.UUID, user: CaseworkUser, session: SessionDep, storage: StorageDep
) -> Response:
    """Download, verifying the hash first. Always served as an attachment inside a sandbox
    CSP, because archived pages are hostile content."""
    evidence, case = await get_evidence(session, user, evidence_id)
    if evidence.storage_key is None:
        raise conflict("no_content", "this evidence item has no stored content")
    try:
        data, result = await evidence_service.read_and_verify(storage, evidence)
    except ObjectMissingError as exc:
        raise conflict("integrity_failure", "stored object is missing") from exc
    if not result.match:
        await audit.record(
            session,
            org_id=case.org_id,
            actor_id=user.id,
            action="evidence.integrity_failure",
            target_type="evidence",
            target_id=evidence.id,
            payload={"case_id": str(case.id), "expected": result.expected, "actual": result.actual},
        )
        await session.commit()
        raise conflict("integrity_failure", "stored content does not match its capture hash")
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="evidence.access",
        target_type="evidence",
        target_id=evidence.id,
        payload={"case_id": str(case.id)},
    )
    await session.commit()
    filename = evidence.original_filename or f"evidence-{evidence.id}"
    return Response(
        content=data,
        media_type=evidence.mime or "application/octet-stream",
        headers={
            "Content-Disposition": f"attachment; filename*=UTF-8''{quote(filename)}",
            "Content-Security-Policy": "sandbox; default-src 'none'",
            "X-Content-SHA256": result.actual,
        },
    )


@router.post("/evidence/{evidence_id}/exclude", response_model=EvidenceOut)
async def exclude_evidence(
    evidence_id: uuid.UUID, body: ExcludeRequest, user: CaseworkUser, session: SessionDep
) -> Evidence:
    evidence, case = await get_evidence(session, user, evidence_id)
    ensure_writable(user, case)
    if evidence.excluded:
        raise conflict("already_excluded", "evidence is already excluded")
    evidence.excluded = True
    evidence.excluded_reason = body.reason.strip()
    evidence.excluded_at = datetime.now(UTC)
    evidence.excluded_by = user.id
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="evidence.exclude",
        target_type="evidence",
        target_id=evidence.id,
        payload={"case_id": str(case.id), "reason": evidence.excluded_reason},
    )
    await session.commit()
    return evidence
