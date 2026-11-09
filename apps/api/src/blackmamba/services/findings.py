"""Findings (FR-6) and verification (FR-7).

draft -> in_review -> verified | rejected; rejected -> draft (author revises).
- A finding needs >= 1 non-excluded evidence item of the same case (422 otherwise).
- Only reviewers verify/reject, and never their own finding (403) - enforced here, server side.
- Rejection needs a reason. Verified findings are frozen (also enforced by a DB trigger).
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from sqlalchemy import delete, insert, select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.api.deps import conflict, forbidden, not_found, unprocessable
from blackmamba.models import (
    Case,
    Evidence,
    EvidenceType,
    Finding,
    FindingStatus,
    Role,
    User,
    finding_evidence,
)
from blackmamba.services import audit


async def get_finding(
    session: AsyncSession, user: User, finding_id: uuid.UUID
) -> tuple[Finding, Case]:
    row = (
        await session.execute(
            select(Finding, Case)
            .join(Case, Case.id == Finding.case_id)
            .where(Finding.id == finding_id, Case.org_id == user.org_id)
        )
    ).first()
    if row is None:
        raise not_found("finding")
    return row


async def evidence_ids_of(session: AsyncSession, finding_id: uuid.UUID) -> list[uuid.UUID]:
    rows = await session.scalars(
        select(finding_evidence.c.evidence_id).where(finding_evidence.c.finding_id == finding_id)
    )
    return list(rows)


async def _validate_evidence(
    session: AsyncSession, case: Case, evidence_ids: Sequence[uuid.UUID]
) -> list[uuid.UUID]:
    unique = list(dict.fromkeys(evidence_ids))
    if not unique:
        raise unprocessable("evidence_required", "a finding must cite at least one evidence item")
    rows = (
        await session.scalars(
            select(Evidence).where(Evidence.id.in_(unique), Evidence.case_id == case.id)
        )
    ).all()
    if len(rows) != len(unique):
        raise unprocessable("invalid_evidence", "evidence must belong to this case")
    if any(e.excluded for e in rows):
        raise unprocessable("excluded_evidence", "excluded evidence cannot support a finding")
    if any(e.type == EvidenceType.REPORT for e in rows):
        raise unprocessable("invalid_evidence", "reports cannot be cited as evidence")
    return unique


async def _link(
    session: AsyncSession, finding_id: uuid.UUID, evidence_ids: list[uuid.UUID]
) -> None:
    await session.execute(
        delete(finding_evidence).where(finding_evidence.c.finding_id == finding_id)
    )
    await session.execute(
        insert(finding_evidence),
        [{"finding_id": finding_id, "evidence_id": eid} for eid in evidence_ids],
    )


async def create(
    session: AsyncSession,
    *,
    case: Case,
    author: User,
    claim: str,
    evidence_ids: Sequence[uuid.UUID],
) -> Finding:
    ids = await _validate_evidence(session, case, evidence_ids)
    finding = Finding(case_id=case.id, claim=claim.strip(), author_id=author.id)
    session.add(finding)
    await session.flush()
    await _link(session, finding.id, ids)
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=author.id,
        action="finding.create",
        target_type="finding",
        target_id=finding.id,
        payload={"case_id": str(case.id), "evidence_ids": [str(i) for i in ids]},
    )
    return finding


def _ensure_author_can_edit(finding: Finding, user: User) -> None:
    if finding.author_id != user.id:
        raise forbidden("not_author", "only the author can change this finding")
    if finding.status not in {FindingStatus.DRAFT, FindingStatus.REJECTED}:
        raise conflict("invalid_state", f"a {finding.status.value} finding cannot be edited")


async def update(
    session: AsyncSession,
    *,
    finding: Finding,
    case: Case,
    user: User,
    claim: str | None,
    evidence_ids: Sequence[uuid.UUID] | None,
) -> Finding:
    _ensure_author_can_edit(finding, user)
    changes: dict[str, object] = {}
    if claim is not None and claim.strip() != finding.claim:
        finding.claim = claim.strip()
        changes["claim"] = "changed"
    if evidence_ids is not None:
        ids = await _validate_evidence(session, case, evidence_ids)
        await _link(session, finding.id, ids)
        changes["evidence_ids"] = [str(i) for i in ids]
    if finding.status == FindingStatus.REJECTED:
        finding.status = FindingStatus.DRAFT  # revising a rejected finding reopens it as draft
        changes["status"] = {"from": "rejected", "to": "draft"}
    if changes:
        await audit.record(
            session,
            org_id=case.org_id,
            actor_id=user.id,
            action="finding.update",
            target_type="finding",
            target_id=finding.id,
            payload={"case_id": str(case.id), "changes": changes},
        )
    return finding


async def submit(session: AsyncSession, *, finding: Finding, case: Case, user: User) -> Finding:
    _ensure_author_can_edit(finding, user)
    if finding.status != FindingStatus.DRAFT:
        raise conflict("invalid_state", "only draft findings can be submitted")
    # Re-check: evidence may have been excluded since the finding was written.
    await _validate_evidence(session, case, await evidence_ids_of(session, finding.id))
    finding.status = FindingStatus.IN_REVIEW
    finding.submitted_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="finding.submit",
        target_type="finding",
        target_id=finding.id,
        payload={"case_id": str(case.id)},
    )
    return finding


def _ensure_can_review(finding: Finding, reviewer: User) -> None:
    if reviewer.role != Role.REVIEWER:
        raise forbidden("reviewer_required", "only reviewers can verify or reject findings")
    if finding.author_id == reviewer.id:
        raise forbidden("self_review", "you cannot review your own finding")
    if finding.status != FindingStatus.IN_REVIEW:
        raise conflict("invalid_state", "only findings in review can be decided")


async def verify(
    session: AsyncSession, *, finding: Finding, case: Case, reviewer: User, note: str | None
) -> Finding:
    _ensure_can_review(finding, reviewer)
    await _validate_evidence(session, case, await evidence_ids_of(session, finding.id))
    finding.status = FindingStatus.VERIFIED
    finding.reviewer_id = reviewer.id
    finding.review_note = note.strip() if note else None
    finding.reviewed_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=reviewer.id,
        action="finding.verify",
        target_type="finding",
        target_id=finding.id,
        payload={"case_id": str(case.id), "author_id": str(finding.author_id)},
    )
    return finding


async def reject(
    session: AsyncSession, *, finding: Finding, case: Case, reviewer: User, reason: str
) -> Finding:
    _ensure_can_review(finding, reviewer)
    if not reason.strip():
        raise unprocessable("reason_required", "a rejection needs a reason")
    finding.status = FindingStatus.REJECTED
    finding.reviewer_id = reviewer.id
    finding.review_note = reason.strip()
    finding.reviewed_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=reviewer.id,
        action="finding.reject",
        target_type="finding",
        target_id=finding.id,
        payload={"case_id": str(case.id), "reason": finding.review_note},
    )
    return finding
