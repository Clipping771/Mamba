"""Run the ARCHIVIST agent on a case (FR-10). Output is saved as an AI-draft note only."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, status
from sqlalchemy import select

from blackmamba.agents.archivist import ArchivistInput, run_archivist
from blackmamba.agents.llm import LLMClient, LLMError, get_llm
from blackmamba.api.deps import CaseworkUser, SessionDep, http_error
from blackmamba.models import AI_DRAFT_LABEL, Evidence, EvidenceType, Note
from blackmamba.schemas.cases import NoteOut
from blackmamba.services import audit
from blackmamba.services.cases import ensure_writable, get_case

router = APIRouter(tags=["archivist"])

LLMDep = Annotated[LLMClient, Depends(get_llm)]


@router.post("/cases/{case_id}/archivist", response_model=NoteOut, status_code=201)
async def run_case_archivist(
    case_id: uuid.UUID, user: CaseworkUser, session: SessionDep, llm: LLMDep
) -> NoteOut:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    evidence = (
        await session.scalars(
            select(Evidence)
            .where(
                Evidence.case_id == case.id,
                Evidence.excluded.is_(False),
                Evidence.type != EvidenceType.REPORT,
            )
            .order_by(Evidence.captured_at)
        )
    ).all()
    # Human notes only: AI drafts are never fed back in as if they were facts.
    notes = (
        await session.scalars(
            select(Note).where(Note.case_id == case.id, Note.is_ai_draft.is_(False))
        )
    ).all()
    data: ArchivistInput = {
        "case_title": case.title,
        "case_category": case.category.value,
        "case_description": case.description,
        "evidence": [
            {
                "ref": f"E{i + 1}",
                "type": e.type.value,
                "title": e.title,
                "description": e.description,
                "source_url": e.source_url,
                "final_url": e.final_url,
                "http_status": e.http_status,
                "captured_at": e.captured_at,
            }
            for i, e in enumerate(evidence)
        ],
        "notes": [{"body": n.body, "created_at": n.created_at} for n in notes],
    }
    try:
        body = await run_archivist(llm, data)
    except LLMError as exc:
        raise http_error(status.HTTP_502_BAD_GATEWAY, "llm_error", str(exc)) from exc

    note = Note(
        case_id=case.id,
        body=body,
        is_ai_draft=True,
        ai_model=llm.model_name,
        author_id=user.id,
    )
    session.add(note)
    await session.flush()
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="archivist.run",
        target_type="note",
        target_id=note.id,
        payload={
            "case_id": str(case.id),
            "is_ai_draft": True,
            "model": llm.model_name,
            "evidence_items": len(evidence),
        },
    )
    await session.commit()
    await session.refresh(note)
    out = NoteOut.model_validate(note)
    out.label = AI_DRAFT_LABEL
    return out
