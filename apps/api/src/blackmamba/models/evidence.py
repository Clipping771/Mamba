import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import BigInteger, Boolean, DateTime, ForeignKey, Integer, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from blackmamba.models.base import Base, str_enum


class EvidenceType(StrEnum):
    URL = "url"
    FILE = "file"
    SCREENSHOT = "screenshot"
    NOTE = "note"
    REPORT = "report"


class Evidence(Base):
    """Immutable (FR-3/NFR-2). A DB trigger forbids DELETE and any UPDATE except exclusion."""

    __tablename__ = "evidence"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="RESTRICT"), index=True
    )
    type: Mapped[EvidenceType] = mapped_column(str_enum(EvidenceType, "evidence_type"))
    title: Mapped[str] = mapped_column(String(300), default="")
    description: Mapped[str] = mapped_column(Text, default="")
    source_url: Mapped[str | None] = mapped_column(Text, default=None)
    final_url: Mapped[str | None] = mapped_column(Text, default=None)
    http_status: Mapped[int | None] = mapped_column(Integer, default=None)
    storage_key: Mapped[str | None] = mapped_column(String(500), unique=True, default=None)
    sha256: Mapped[str | None] = mapped_column(String(64), default=None)
    size: Mapped[int | None] = mapped_column(BigInteger, default=None)
    mime: Mapped[str | None] = mapped_column(String(255), default=None)
    original_filename: Mapped[str | None] = mapped_column(String(300), default=None)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    captured_by: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT")
    )
    archive_job_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("archive_jobs.id", ondelete="RESTRICT"), default=None, index=True
    )
    excluded: Mapped[bool] = mapped_column(Boolean, default=False)
    excluded_reason: Mapped[str | None] = mapped_column(Text, default=None)
    excluded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
    excluded_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), default=None
    )
