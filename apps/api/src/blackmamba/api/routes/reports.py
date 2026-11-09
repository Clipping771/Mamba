"""Case reports (FR-8): HTML preview and hashed PDF stored as evidence."""

import asyncio
import uuid

from fastapi import APIRouter, status
from pydantic import BaseModel

from blackmamba.api.deps import CaseworkUser, ReviewerUser, SessionDep, http_error
from blackmamba.models import Evidence, EvidenceType
from blackmamba.schemas.cases import EvidenceOut
from blackmamba.services import audit, report
from blackmamba.services.cases import get_case
from blackmamba.services.evidence import store_content

from .evidence import StorageDep

router = APIRouter(tags=["reports"])


class ReportPreview(BaseModel):
    html: str
    verified_findings: int
    evidence_items: int
    chain_ok: bool
    pdf_available: bool


@router.get("/cases/{case_id}/report/preview", response_model=ReportPreview)
async def preview_report(
    case_id: uuid.UUID, user: CaseworkUser, session: SessionDep
) -> ReportPreview:
    """Rendered HTML of the report. Clients must show it in a sandboxed iframe (srcdoc)."""
    case = await get_case(session, user, case_id)
    context = await report.build_context(session, case, user)
    return ReportPreview(
        html=report.render_html(context),
        verified_findings=len(context.findings),
        evidence_items=len(context.evidence),
        chain_ok=context.chain_ok,
        pdf_available=report.pdf_engine_available(),
    )


@router.post("/cases/{case_id}/reports", response_model=EvidenceOut, status_code=201)
async def generate_report(
    case_id: uuid.UUID, user: ReviewerUser, session: SessionDep, storage: StorageDep
) -> Evidence:
    case = await get_case(session, user, case_id)
    context = await report.build_context(session, case, user)
    if not context.chain_ok:
        raise http_error(
            status.HTTP_409_CONFLICT,
            "audit_chain_broken",
            "the audit chain failed verification; investigate before reporting",
        )
    html = report.render_html(context)
    try:
        pdf = await asyncio.to_thread(report.render_pdf, html)
    except report.PdfEngineUnavailableError as exc:
        raise http_error(status.HTTP_503_SERVICE_UNAVAILABLE, "pdf_unavailable", str(exc)) from exc
    evidence = await store_content(
        session,
        storage,
        case=case,
        actor=user,
        captured_by=user.id,
        type=EvidenceType.REPORT,
        data=pdf,
        mime="application/pdf",
        title=f"Case report {context.generated_at:%Y-%m-%d %H:%M} UTC",
        original_filename=f"report-{case.id}-{context.report_id}.pdf",
    )
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="report.generate",
        target_type="evidence",
        target_id=evidence.id,
        payload={
            "case_id": str(case.id),
            "sha256": evidence.sha256,
            "verified_findings": [f["id"] for f in context.findings],
            "report_id": context.report_id,
        },
    )
    await session.commit()
    return evidence
