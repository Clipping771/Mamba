"""Auto-archive requests and job status (FR-4)."""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy import select

from blackmamba.api.deps import CaseworkUser, SessionDep, not_found, unprocessable
from blackmamba.core.config import get_settings
from blackmamba.models import ArchiveJob, Case, Evidence
from blackmamba.schemas.cases import ArchiveJobOut, ArchiveRequest
from blackmamba.services import audit
from blackmamba.services.cases import ensure_writable, get_case
from blackmamba.services.queue import JobQueue, get_job_queue
from blackmamba.services.url_safety import UnsafeUrlError, ensure_public_url

router = APIRouter(tags=["archive"])

QueueDep = Annotated[JobQueue, Depends(get_job_queue)]


async def _out(session: SessionDep, job: ArchiveJob) -> ArchiveJobOut:
    out = ArchiveJobOut.model_validate(job)
    out.evidence_ids = list(
        await session.scalars(
            select(Evidence.id).where(Evidence.archive_job_id == job.id).order_by(Evidence.type)
        )
    )
    return out


@router.post("/cases/{case_id}/archive", response_model=ArchiveJobOut, status_code=202)
async def request_archive(
    case_id: uuid.UUID,
    body: ArchiveRequest,
    user: CaseworkUser,
    session: SessionDep,
    queue: QueueDep,
) -> ArchiveJobOut:
    case = await get_case(session, user, case_id)
    ensure_writable(user, case)
    try:
        url = await ensure_public_url(
            body.url, allow_private=get_settings().archive_allow_private_hosts
        )
    except UnsafeUrlError as exc:
        raise unprocessable("unsafe_url", str(exc)) from exc
    job = ArchiveJob(case_id=case.id, url=url, created_by=user.id)
    session.add(job)
    await session.flush()
    await audit.record(
        session,
        org_id=case.org_id,
        actor_id=user.id,
        action="archive.request",
        target_type="archive_job",
        target_id=job.id,
        payload={"case_id": str(case.id), "url": url},
    )
    await session.commit()
    await session.refresh(job)
    queue.enqueue_archive(job.id)
    return await _out(session, job)


@router.get("/cases/{case_id}/archive-jobs", response_model=list[ArchiveJobOut])
async def list_archive_jobs(
    case_id: uuid.UUID, user: CaseworkUser, session: SessionDep
) -> list[ArchiveJobOut]:
    case = await get_case(session, user, case_id)
    jobs = await session.scalars(
        select(ArchiveJob)
        .where(ArchiveJob.case_id == case.id)
        .order_by(ArchiveJob.created_at.desc())
    )
    return [await _out(session, job) for job in jobs]


@router.get("/archive-jobs/{job_id}", response_model=ArchiveJobOut)
async def read_archive_job(
    job_id: uuid.UUID, user: CaseworkUser, session: SessionDep
) -> ArchiveJobOut:
    job = await session.scalar(
        select(ArchiveJob)
        .join(Case, Case.id == ArchiveJob.case_id)
        .where(ArchiveJob.id == job_id, Case.org_id == user.org_id)
    )
    if job is None:
        raise not_found("archive job")
    return await _out(session, job)
