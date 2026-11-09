import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column

from blackmamba.models.base import Base, str_enum, utc_now_column


class CaseStatus(StrEnum):
    OPEN = "open"
    INVESTIGATING = "investigating"
    REVIEW = "review"
    CLOSED = "closed"


class CaseCategory(StrEnum):
    JOB_SCAM = "job_scam"
    INVESTMENT_SCAM = "investment_scam"
    PHISHING = "phishing"
    MARKETPLACE = "marketplace"
    ROMANCE_SCAM = "romance_scam"
    IMPERSONATION = "impersonation"
    OTHER = "other"


class Case(Base):
    __tablename__ = "cases"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), index=True
    )
    title: Mapped[str] = mapped_column(String(300))
    category: Mapped[CaseCategory] = mapped_column(str_enum(CaseCategory, "case_category"))
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[CaseStatus] = mapped_column(
        str_enum(CaseStatus, "case_status"), default=CaseStatus.OPEN, index=True
    )
    lead_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), index=True
    )
    created_at: Mapped[datetime] = utc_now_column()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now()
    )
