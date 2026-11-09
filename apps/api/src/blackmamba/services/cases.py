"""Case access rules and status workflow (FR-2).

Access model (docs/adr/ADR-002-saas-tenancy-and-access.md):
- Everything is scoped to the caller's organisation; other orgs' cases are 404.
- Investigators and reviewers can read every case in their org.
- Writing to a case (edit, evidence, notes, findings, archive) is allowed for the case lead
  and for reviewers. Closed cases are read-only (409) until a reviewer reopens them.
"""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.api.deps import conflict, forbidden, not_found
from blackmamba.models import Case, CaseStatus, Role, User

TRANSITIONS: dict[CaseStatus, frozenset[CaseStatus]] = {
    CaseStatus.OPEN: frozenset({CaseStatus.INVESTIGATING}),
    CaseStatus.INVESTIGATING: frozenset({CaseStatus.REVIEW}),
    CaseStatus.REVIEW: frozenset({CaseStatus.CLOSED, CaseStatus.INVESTIGATING}),
    CaseStatus.CLOSED: frozenset({CaseStatus.OPEN}),  # reopen: reviewers only
}


async def get_case(session: AsyncSession, user: User, case_id: uuid.UUID) -> Case:
    case = await session.get(Case, case_id)
    if case is None or case.org_id != user.org_id:
        raise not_found("case")
    return case


def can_write(user: User, case: Case) -> bool:
    return user.id == case.lead_id or user.role == Role.REVIEWER


def ensure_writable(user: User, case: Case) -> None:
    if not can_write(user, case):
        raise forbidden("not_case_lead", "only the case lead or a reviewer can change this case")
    if case.status == CaseStatus.CLOSED:
        raise conflict("case_closed", "the case is closed; a reviewer must reopen it first")


def allowed_transitions(user: User, case: Case) -> list[CaseStatus]:
    if not can_write(user, case):
        return []
    targets = TRANSITIONS[case.status]
    if case.status == CaseStatus.CLOSED and user.role != Role.REVIEWER:
        return []
    return sorted(targets)


def check_transition(user: User, case: Case, target: CaseStatus) -> None:
    if target not in TRANSITIONS[case.status]:
        raise conflict("invalid_transition", f"cannot move a case from {case.status} to {target}")
    if case.status == CaseStatus.CLOSED and user.role != Role.REVIEWER:
        raise forbidden("reviewer_required", "only a reviewer can reopen a closed case")
    if not can_write(user, case):
        raise forbidden("not_case_lead", "only the case lead or a reviewer can change this case")


async def get_org_member(
    session: AsyncSession, org_id: uuid.UUID, user_id: uuid.UUID
) -> User | None:
    return await session.scalar(
        select(User).where(
            User.id == user_id,
            User.org_id == org_id,
            User.is_active.is_(True),
            User.role.in_([Role.INVESTIGATOR, Role.REVIEWER]),
        )
    )
