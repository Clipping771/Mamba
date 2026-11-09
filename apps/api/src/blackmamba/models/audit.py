import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import BigInteger, DateTime, ForeignKey, Index, String, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column

from blackmamba.models.base import Base


class AuditLog(Base):
    """Append-only, hash-chained (FR-9). One chain per organisation (org_id NULL = platform
    chain). DB triggers forbid UPDATE/DELETE/TRUNCATE."""

    __tablename__ = "audit_log"
    __table_args__ = (
        Index("ix_audit_log_target", "target_type", "target_id"),
        Index("ix_audit_log_org_id_id", "org_id", "id"),
    )

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), default=None
    )
    actor_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), default=None
    )
    action: Mapped[str] = mapped_column(String(100))
    target_type: Mapped[str | None] = mapped_column(String(50), default=None)
    target_id: Mapped[str | None] = mapped_column(String(100), default=None)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64), unique=True)
