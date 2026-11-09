import uuid
from datetime import datetime
from typing import Any

from pydantic import AnyHttpUrl, BaseModel, Field

from blackmamba.models import (
    ArchiveJobStatus,
    CaseCategory,
    CaseStatus,
    EvidenceType,
    FindingStatus,
)
from blackmamba.schemas.common import ORMModel


# ------------------------------------------------------------------ cases
class CaseCreate(BaseModel):
    title: str = Field(min_length=3, max_length=300)
    category: CaseCategory
    description: str = Field(default="", max_length=20000)
    lead_id: uuid.UUID | None = None


class CaseUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=3, max_length=300)
    category: CaseCategory | None = None
    description: str | None = Field(default=None, max_length=20000)
    lead_id: uuid.UUID | None = None


class CaseTransition(BaseModel):
    status: CaseStatus


class CaseOut(ORMModel):
    id: uuid.UUID
    title: str
    category: CaseCategory
    description: str
    status: CaseStatus
    lead_id: uuid.UUID
    created_at: datetime
    updated_at: datetime


class CaseSummary(CaseOut):
    lead_name: str
    evidence_count: int = 0
    finding_counts: dict[str, int] = {}
    can_edit: bool = False
    allowed_transitions: list[CaseStatus] = []


# ------------------------------------------------------------------ evidence
class EvidenceOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    type: EvidenceType
    title: str
    description: str
    source_url: str | None
    final_url: str | None
    http_status: int | None
    sha256: str | None
    size: int | None
    mime: str | None
    original_filename: str | None
    captured_at: datetime
    captured_by: uuid.UUID
    archive_job_id: uuid.UUID | None
    excluded: bool
    excluded_reason: str | None
    excluded_at: datetime | None
    excluded_by: uuid.UUID | None


class UrlEvidenceCreate(BaseModel):
    url: AnyHttpUrl
    title: str = Field(default="", max_length=300)
    description: str = Field(default="", max_length=10000)


class NoteEvidenceCreate(BaseModel):
    title: str = Field(min_length=1, max_length=300)
    body: str = Field(min_length=1, max_length=100000)


class ExcludeRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=2000)


class VerifyOut(BaseModel):
    evidence_id: uuid.UUID
    algorithm: str = "sha256"
    expected: str
    actual: str
    match: bool
    verified_at: datetime


# ------------------------------------------------------------------ notes
class NoteCreate(BaseModel):
    body: str = Field(min_length=1, max_length=50000)


class NoteOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    body: str
    is_ai_draft: bool
    ai_model: str | None
    author_id: uuid.UUID
    created_at: datetime
    label: str | None = None


# ------------------------------------------------------------------ archive jobs
class ArchiveRequest(BaseModel):
    url: str = Field(min_length=8, max_length=4000)


class ArchiveJobOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    url: str
    status: ArchiveJobStatus
    error: str | None
    created_by: uuid.UUID
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    evidence_ids: list[uuid.UUID] = []


# ------------------------------------------------------------------ findings
class FindingCreate(BaseModel):
    claim: str = Field(min_length=10, max_length=10000)
    evidence_ids: list[uuid.UUID] = Field(min_length=1, max_length=200)


class FindingUpdate(BaseModel):
    claim: str | None = Field(default=None, min_length=10, max_length=10000)
    evidence_ids: list[uuid.UUID] | None = Field(default=None, min_length=1, max_length=200)


class RejectRequest(BaseModel):
    reason: str = Field(min_length=5, max_length=5000)


class VerifyFindingRequest(BaseModel):
    note: str | None = Field(default=None, max_length=5000)


class FindingOut(ORMModel):
    id: uuid.UUID
    case_id: uuid.UUID
    claim: str
    status: FindingStatus
    author_id: uuid.UUID
    reviewer_id: uuid.UUID | None
    review_note: str | None
    created_at: datetime
    updated_at: datetime
    submitted_at: datetime | None
    reviewed_at: datetime | None
    evidence_ids: list[uuid.UUID] = []


class ReviewQueueItem(FindingOut):
    case_title: str
    author_name: str


# ------------------------------------------------------------------ activity / users
class ActivityOut(ORMModel):
    id: int
    actor_id: uuid.UUID | None
    actor_name: str | None = None
    action: str
    target_type: str | None
    target_id: str | None
    payload: dict[str, Any]
    ts: datetime
    hash: str


class MemberOut(ORMModel):
    id: uuid.UUID
    name: str
    role: str
