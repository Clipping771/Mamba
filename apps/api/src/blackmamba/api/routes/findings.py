"""Findings (FR-6) and the review workflow (FR-7)."""

import uuid

from fastapi import APIRouter
from sqlalchemy import select

from blackmamba.api.deps import CaseworkUser, ReviewerUser, SessionDep
from blackmamba.models import Case, Finding, FindingStatus, User
from blackmamba.schemas.cases import (
    FindingCreate,
    FindingOut,
    FindingUpdate,
    RejectRequest,
    ReviewQueueItem,
    VerifyFindingRequest,
)
from blackmamba.services import findings as service
from blackmamba.services.cases import ensure_writable, get_case

router = APIRouter(tags=["findings"])


async def _out(session: SessionDep, finding: Finding) -> FindingOut:
    out = FindingOut.model_validate(finding)
    out.evidence_ids = await service.evidence_ids_of(session, finding.id)
    return out


@router.get("/cases/{case_id}/findings", response_model=list[FindingOut])
async def list_findings(
    case_id: uuid.UUID, user: CaseworkUser, session: SessionDep, status: FindingStatus | None = None
) -> list[FindingOut]:
    case = await get_case(session, user, case_id)
    query = select(Finding).where(Finding.case_id == case.id)
    if status is not None:
        query = query.where(Finding.status == status)
    return [
        await _out(session, f) for f in await session.scalars(query.order_by(Finding.created_at))
    ]


@router.post("/cases/{case_id}/findings", response_model=FindingOut, status_code=201)
async def create_finding(
    case_id: uuid.UUID, body: FindingCreate, user: CaseworkUser, session: SessionDep
) -> FindingOut:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    finding = await service.create(
        session, case=case, author=user, claim=body.claim, evidence_ids=body.evidence_ids
    )
    await session.commit()
    await session.refresh(finding)
    return await _out(session, finding)


@router.get("/findings/review-queue", response_model=list[ReviewQueueItem])
async def review_queue(user: ReviewerUser, session: SessionDep) -> list[ReviewQueueItem]:
    """Findings awaiting review in the reviewer's org, excluding their own."""
    rows = await session.execute(
        select(Finding, Case.title, User.name)
        .join(Case, Case.id == Finding.case_id)
        .join(User, User.id == Finding.author_id)
        .where(
            Case.org_id == user.org_id,
            Finding.status == FindingStatus.IN_REVIEW,
            Finding.author_id != user.id,
        )
        .order_by(Finding.submitted_at)
    )
    items = []
    for finding, case_title, author_name in rows:
        base = await _out(session, finding)
        items.append(
            ReviewQueueItem(**base.model_dump(), case_title=case_title, author_name=author_name)
        )
    return items


@router.get("/findings/{finding_id}", response_model=FindingOut)
async def read_finding(
    finding_id: uuid.UUID, user: CaseworkUser, session: SessionDep
) -> FindingOut:
    finding, _ = await service.get_finding(session, user, finding_id)
    return await _out(session, finding)


@router.patch("/findings/{finding_id}", response_model=FindingOut)
async def update_finding(
    finding_id: uuid.UUID, body: FindingUpdate, user: CaseworkUser, session: SessionDep
) -> FindingOut:
    finding, case = await service.get_finding(session, user, finding_id)
    ensure_writable(user, case)
    await service.update(
        session,
        finding=finding,
        case=case,
        user=user,
        claim=body.claim,
        evidence_ids=body.evidence_ids,
    )
    await session.commit()
    await session.refresh(finding)
    return await _out(session, finding)


@router.post("/findings/{finding_id}/submit", response_model=FindingOut)
async def submit_finding(
    finding_id: uuid.UUID, user: CaseworkUser, session: SessionDep
) -> FindingOut:
    finding, case = await service.get_finding(session, user, finding_id)
    ensure_writable(user, case)
    await service.submit(session, finding=finding, case=case, user=user)
    await session.commit()
    await session.refresh(finding)
    return await _out(session, finding)


@router.post("/findings/{finding_id}/verify", response_model=FindingOut)
async def verify_finding(
    finding_id: uuid.UUID,
    user: CaseworkUser,
    session: SessionDep,
    body: VerifyFindingRequest | None = None,
) -> FindingOut:
    # Role and author != reviewer are checked in the service (403), not just by the route.
    finding, case = await service.get_finding(session, user, finding_id)
    await service.verify(
        session, finding=finding, case=case, reviewer=user, note=body.note if body else None
    )
    await session.commit()
    await session.refresh(finding)
    return await _out(session, finding)


@router.post("/findings/{finding_id}/reject", response_model=FindingOut)
async def reject_finding(
    finding_id: uuid.UUID, body: RejectRequest, user: CaseworkUser, session: SessionDep
) -> FindingOut:
    finding, case = await service.get_finding(session, user, finding_id)
    await service.reject(session, finding=finding, case=case, reviewer=user, reason=body.reason)
    await session.commit()
    await session.refresh(finding)
    return await _out(session, finding)
