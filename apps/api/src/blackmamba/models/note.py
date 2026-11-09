import uuid
from datetime import datetime

from sqlalchemy import Boolean, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from blackmamba.models.base import Base, utc_now_column

AI_DRAFT_LABEL = "AI draft — not verified"


class Note(Base):
    """Working notes. AI output (FR-10) lives here with is_ai_draft=true. Findings link
    evidence only, and reports render findings + evidence only, so AI drafts can never be
    verified or reported."""

    __tablename__ = "notes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    case_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("cases.id", ondelete="RESTRICT"), index=True
    )
    body: Mapped[str] = mapped_column(Text)
    is_ai_draft: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_model: Mapped[str | None] = mapped_column(String(200), default=None)
    author_id: Mapped[uuid.UUID] = mapped_column(Uuid, ForeignKey("users.id", ondelete="RESTRICT"))
    created_at: Mapped[datetime] = utc_now_column()
