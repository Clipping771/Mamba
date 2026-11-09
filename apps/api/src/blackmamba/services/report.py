"""Case PDF report (FR-8).

The report contains ONLY verified findings. Draft/in-review/rejected findings and notes
(including every AI draft) are never queried here, so they cannot leak into a report.
The PDF is hashed and stored as evidence of type `report`.
"""

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, select_autoescape
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba import __version__
from blackmamba.models import (
    AuditLog,
    Case,
    Evidence,
    EvidenceType,
    Finding,
    FindingStatus,
    Organization,
    User,
    finding_evidence,
)
from blackmamba.services import audit

TEMPLATES = Path(__file__).resolve().parent.parent / "templates"
_env = Environment(
    loader=FileSystemLoader(TEMPLATES),
    autoescape=select_autoescape(["html"]),
    trim_blocks=True,
    lstrip_blocks=True,
)

CUSTODY_ACTIONS = (
    "evidence.capture",
    "evidence.verify",
    "evidence.access",
    "evidence.exclude",
    "evidence.integrity_failure",
    "finding.verify",
    "report.generate",
)


class PdfEngineUnavailableError(RuntimeError):
    pass


@dataclass
class ReportContext:
    org_name: str
    case: Case
    lead_name: str
    generated_at: datetime
    generated_by: str
    findings: list[dict[str, Any]]
    evidence: list[dict[str, Any]]
    excluded: list[dict[str, Any]]
    custody: list[dict[str, Any]]
    chain_ok: bool
    chain_entries: int
    version: str = __version__
    report_id: str = field(default_factory=lambda: uuid.uuid4().hex[:12])


def _short(value: uuid.UUID | str) -> str:
    return str(value)[:8]


async def build_context(session: AsyncSession, case: Case, generated_by: User) -> ReportContext:
    org = await session.get(Organization, case.org_id)
    users = {
        u.id: u.name for u in await session.scalars(select(User).where(User.org_id == case.org_id))
    }

    all_evidence = (
        await session.scalars(
            select(Evidence)
            .where(Evidence.case_id == case.id, Evidence.type != EvidenceType.REPORT)
            .order_by(Evidence.captured_at)
        )
    ).all()
    numbers = {e.id: f"E{i + 1}" for i, e in enumerate(all_evidence)}

    def evidence_row(e: Evidence) -> dict[str, Any]:
        return {
            "ref": numbers[e.id],
            "id": str(e.id),
            "type": e.type.value,
            "title": e.title or "(untitled)",
            "source_url": e.source_url,
            "final_url": e.final_url if e.final_url != e.source_url else None,
            "http_status": e.http_status,
            "sha256": e.sha256,
            "size": e.size,
            "mime": e.mime,
            "captured_at": e.captured_at.astimezone(UTC),
            "captured_by": users.get(e.captured_by, _short(e.captured_by)),
            "excluded_reason": e.excluded_reason,
        }

    # ---- verified findings only (FR-8)
    verified = (
        await session.scalars(
            select(Finding)
            .where(Finding.case_id == case.id, Finding.status == FindingStatus.VERIFIED)
            .order_by(Finding.reviewed_at)
        )
    ).all()
    findings = []
    for i, f in enumerate(verified):
        cited = await session.scalars(
            select(finding_evidence.c.evidence_id).where(finding_evidence.c.finding_id == f.id)
        )
        findings.append(
            {
                "ref": f"F{i + 1}",
                "id": str(f.id),
                "claim": f.claim,
                "author": users.get(f.author_id, _short(f.author_id)),
                "reviewer": users.get(f.reviewer_id, "") if f.reviewer_id else "",
                "reviewed_at": f.reviewed_at,
                "review_note": f.review_note,
                "evidence_refs": sorted(numbers[eid] for eid in cited if eid in numbers),
            }
        )

    # ---- chain of custody from the audit log
    entries = (
        await session.scalars(
            select(AuditLog)
            .where(
                AuditLog.org_id == case.org_id,
                AuditLog.payload["case_id"].astext == str(case.id),
                AuditLog.action.in_(CUSTODY_ACTIONS),
            )
            .order_by(AuditLog.id)
        )
    ).all()
    custody = [
        {
            "ts": entry.ts.astimezone(UTC),
            "action": entry.action,
            "subject": numbers.get(uuid.UUID(entry.target_id), entry.target_type or "")
            if entry.target_type == "evidence" and entry.target_id
            else (entry.target_type or ""),
            "actor": users.get(entry.actor_id, "system") if entry.actor_id else "system",
            "detail": _custody_detail(entry),
            "hash": entry.hash[:16],
        }
        for entry in entries
    ]
    chain = await audit.verify_chain(session, case.org_id)

    return ReportContext(
        org_name=org.name if org else "",
        case=case,
        lead_name=users.get(case.lead_id, ""),
        generated_at=datetime.now(UTC),
        generated_by=generated_by.name,
        findings=findings,
        evidence=[evidence_row(e) for e in all_evidence if not e.excluded],
        excluded=[evidence_row(e) for e in all_evidence if e.excluded],
        custody=custody,
        chain_ok=chain.ok,
        chain_entries=chain.entries_checked,
    )


def _custody_detail(entry: AuditLog) -> str:
    p = entry.payload
    if entry.action == "evidence.capture":
        return f"sha256 {str(p.get('sha256') or '-')[:16]}…"
    if entry.action in {"evidence.verify", "evidence.integrity_failure"}:
        return "hash match" if p.get("match") else "HASH MISMATCH"
    if entry.action == "evidence.exclude":
        return f"excluded: {p.get('reason', '')}"
    return ""


def render_html(context: ReportContext) -> str:
    return _env.get_template("report.html").render(r=context)


def render_pdf(html: str) -> bytes:
    try:
        from weasyprint import HTML
    except OSError as exc:  # pragma: no cover - depends on host libraries
        raise PdfEngineUnavailableError("WeasyPrint system libraries are not installed") from exc
    pdf = HTML(string=html, base_url=str(TEMPLATES)).write_pdf()
    if pdf is None:  # pragma: no cover
        raise PdfEngineUnavailableError("WeasyPrint returned no output")
    return bytes(pdf)


def pdf_engine_available() -> bool:
    try:
        import weasyprint  # noqa: F401
    except OSError:
        return False
    return True
