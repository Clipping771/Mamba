"""Cases (FR-2), working notes and case activity (chain of custody view)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, or_, select

from blackmamba.api.deps import CaseworkUser, SessionDep, org_id_of, unprocessable
from blackmamba.models import (
    AI_DRAFT_LABEL,
    AuditLog,
    Case,
    CaseCategory,
    CaseStatus,
    Evidence,
    Finding,
    Note,
    Role,
    User,
)
from blackmamba.schemas.cases import (
    ActivityOut,
    CaseCreate,
    CaseOut,
    CaseSummary,
    CaseTransition,
    CaseUpdate,
    MemberOut,
    NoteCreate,
    NoteOut,
)
from blackmamba.schemas.common import Page
from blackmamba.services import audit
from blackmamba.services.cases import (
    allowed_transitions,
    can_write,
    check_transition,
    ensure_writable,
    get_case,
    get_org_member,
)

router = APIRouter(tags=["cases"])


async def _summary(session: SessionDep, user: User, case: Case) -> CaseSummary:
    lead = await session.get(User, case.lead_id)
    evidence_count = await session.scalar(
        select(func.count()).select_from(Evidence).where(Evidence.case_id == case.id)
    )
    finding_rows = await session.execute(
        select(Finding.status, func.count())
        .where(Finding.case_id == case.id)
        .group_by(Finding.status)
    )
    return CaseSummary(
        **CaseOut.model_validate(case).model_dump(),
        lead_name=lead.name if lead else "unknown",
        evidence_count=evidence_count or 0,
        finding_counts={status.value: count for status, count in finding_rows},
        can_edit=can_write(user, case) and case.status != CaseStatus.CLOSED,
        allowed_transitions=allowed_transitions(user, case),
    )


@router.get("/members", response_model=list[MemberOut])
async def list_members(user: CaseworkUser, session: SessionDep) -> list[User]:
    """Investigators/reviewers of the caller's org (for choosing a case lead)."""
    rows = await session.scalars(
        select(User)
        .where(
            User.org_id == org_id_of(user),
            User.is_active.is_(True),
            User.role.in_([Role.INVESTIGATOR, Role.REVIEWER]),
        )
        .order_by(User.name)
    )
    return list(rows)


@router.get("/cases", response_model=Page[CaseSummary])
async def list_cases(
    user: CaseworkUser,
    session: SessionDep,
    status: CaseStatus | None = None,
    category: CaseCategory | None = None,
    q: Annotated[str | None, Query(max_length=200)] = None,
    mine: bool = False,
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> Page[CaseSummary]:
    query = select(Case).where(Case.org_id == org_id_of(user))
    if status is not None:
        query = query.where(Case.status == status)
    if category is not None:
        query = query.where(Case.category == category)
    if q:
        pattern = f"%{q.replace('%', r'\%').replace('_', r'\_')}%"
        query = query.where(or_(Case.title.ilike(pattern), Case.description.ilike(pattern)))
    if mine:
        query = query.where(Case.lead_id == user.id)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    cases = await session.scalars(
        query.order_by(Case.updated_at.desc()).limit(limit).offset(offset)
    )
    items = [await _summary(session, user, c) for c in cases]
    return Page(items=items, total=total, limit=limit, offset=offset)


@router.post("/cases", response_model=CaseSummary, status_code=201)
async def create_case(body: CaseCreate, user: CaseworkUser, session: SessionDep) -> CaseSummary:
    org_id = org_id_of(user)
    lead_id = body.lead_id or user.id
    if await get_org_member(session, org_id, lead_id) is None:
        raise unprocessable("invalid_lead", "lead must be an active investigator or reviewer")
    case = Case(
        org_id=org_id,
        title=body.title.strip(),
        category=body.category,
        description=body.description.strip(),
        status=CaseStatus.OPEN,
        lead_id=lead_id,
    )
    session.add(case)
    await session.flush()
    await audit.record(
        session,
        org_id=org_id,
        actor_id=user.id,
        action="case.create",
        target_type="case",
        target_id=case.id,
        payload={
            "case_id": str(case.id),
            "title": case.title,
            "category": case.category.value,
            "lead_id": str(lead_id),
        },
    )
    await session.commit()
    await session.refresh(case)
    return await _summary(session, user, case)


@router.get("/cases/{case_id}", response_model=CaseSummary)
async def read_case(case_id: uuid.UUID, user: CaseworkUser, session: SessionDep) -> CaseSummary:
    return await _summary(session, user, await get_case(session, user, case_id))


@router.patch("/cases/{case_id}", response_model=CaseSummary)
async def update_case(
    case_id: uuid.UUID, body: CaseUpdate, user: CaseworkUser, session: SessionDep
) -> CaseSummary:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    changes: dict[str, object] = {}
    if body.title is not None and body.title.strip() != case.title:
        changes["title"] = {"from": case.title, "to": body.title.strip()}
        case.title = body.title.strip()
    if body.category is not None and body.category != case.category:
        changes["category"] = {"from": case.category.value, "to": body.category.value}
        case.category = body.category
    if body.description is not None and body.description.strip() != case.description:
        changes["description"] = "changed"
        case.description = body.description.strip()
    if body.lead_id is not None and body.lead_id != case.lead_id:
        if await get_org_member(session, case.org_id, body.lead_id) is None:
            raise unprocessable("invalid_lead", "lead must be an active investigator or reviewer")
        changes["lead_id"] = {"from": str(case.lead_id), "to": str(body.lead_id)}
        case.lead_id = body.lead_id
    if changes:
        await audit.record(
            session,
            org_id=case.org_id,
            actor_id=user.id,
            action="case.update",
            target_type="case",
            target_id=case.id,
            payload={"case_id": str(case.id), "changes": changes},
        )
        await session.commit()
        await session.refresh(case)
    return await _summary(session, user, case)


@router.post("/cases/{case_id}/transition", response_model=CaseSummary)
async def transition_case(
    case_id: uuid.UUID, body: CaseTransition, user: CaseworkUser, session: SessionDep
) -> CaseSummary:
    case = await get_case(session, user, case_id)
    check_transition(user, case, body.status)
    previous = case.status
    case.status = body.status
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="case.transition",
        target_type="case",
        target_id=case.id,
        payload={"case_id": str(case.id), "from": previous.value, "to": body.status.value},
    )
    await session.commit()
    await session.refresh(case)
    return await _summary(session, user, case)


# ------------------------------------------------------------------ notes
def _note_out(note: Note) -> NoteOut:
    out = NoteOut.model_validate(note)
    out.label = AI_DRAFT_LABEL if note.is_ai_draft else None
    return out


@router.get("/cases/{case_id}/notes", response_model=list[NoteOut])
async def list_notes(case_id: uuid.UUID, user: CaseworkUser, session: SessionDep) -> list[NoteOut]:
    case = await get_case(session, user, case_id)
    rows = await session.scalars(
        select(Note).where(Note.case_id == case.id).order_by(Note.created_at.desc())
    )
    return [_note_out(n) for n in rows]


@router.post("/cases/{case_id}/notes", response_model=NoteOut, status_code=201)
async def create_note(
    case_id: uuid.UUID, body: NoteCreate, user: CaseworkUser, session: SessionDep
) -> NoteOut:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    note = Note(case_id=case.id, body=body.body.strip(), is_ai_draft=False, author_id=user.id)
    session.add(note)
    await session.flush()
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="note.create",
        target_type="note",
        target_id=note.id,
        payload={"case_id": str(case.id), "is_ai_draft": False},
    )
    await session.commit()
    await session.refresh(note)
    return _note_out(note)


# ------------------------------------------------------------------ activity
@router.get("/cases/{case_id}/activity", response_model=list[ActivityOut])
async def case_activity(
    case_id: uuid.UUID,
    user: CaseworkUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=1000)] = 200,
) -> list[ActivityOut]:
    """Audit entries about this case and its evidence/findings/notes (chain of custody)."""
    case = await get_case(session, user, case_id)
    rows = await session.execute(
        select(AuditLog, User.name)
        .outerjoin(User, User.id == AuditLog.actor_id)
        .where(
            AuditLog.org_id == case.org_id,
            AuditLog.payload["case_id"].astext == str(case.id),
        )
        .order_by(AuditLog.id.desc())
        .limit(limit)
    )
    result = []
    for entry, actor_name in rows:
        item = ActivityOut.model_validate(entry)
        item.actor_name = actor_name
        result.append(item)
    return result
