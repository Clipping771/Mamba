import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Column, DateTime, ForeignKey, Table, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from blackmamba.models.base import Base, str_enum, utc_now_column


class FindingStatus(StrEnum):
    DRAFT = "draft"
    IN_REVIEW = "in_review"
    VERIFIED = "verified"
    REJECTED = "rejected"


finding_evidence = Table(
    "finding_evidence",
    Base.metadata,
    Column("finding_id", Uuid, ForeignKey("findings.id", ondelete="CASCADE"), primary_key=True),
    Column("evidence_id", Uuid, ForeignKey("evidence.id", ondelete="RESTRICT"), primary_key=True),
)


class Finding(Base):
    """A human-authored claim backed by >=1 evidence item (FR-6). Only a reviewer who is not
    the author can verify it (FR-7, enforced in services.findings)."""

    __tablename__ = "findings"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="RESTRICT"), index=True
    )
    claim: Mapped[str] = mapped_column(Text)
    status: Mapped[FindingStatus] = mapped_column(
        str_enum(FindingStatus, "finding_status"), default=FindingStatus.DRAFT, index=True
    )
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    reviewer_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), default=None
    )
    review_note: Mapped[str | None] = mapped_column(Text, default=None)
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
