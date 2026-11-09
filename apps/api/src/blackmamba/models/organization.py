import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, String, Text, Uuid
from sqlalchemy.orm import Mapped, mapped_column

from blackmamba.models.base import Base, str_enum, utc_now_column
from blackmamba.models.user import Role


class OrgStatus(StrEnum):
    PENDING = "pending"  # applied, awaiting platform-admin vetting
    ACTIVE = "active"
    SUSPENDED = "suspended"
    REJECTED = "rejected"


class Organization(Base):
    """Tenant. Every case (and everything hanging off it) belongs to exactly one org."""

    __tablename__ = "organizations"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(80), unique=True)
    status: Mapped[OrgStatus] = mapped_column(
        str_enum(OrgStatus, "org_status"), default=OrgStatus.PENDING
    )
    # Application details (minimal: who to contact and why they need access).
    contact_name: Mapped[str] = mapped_column(String(200), default="")
    contact_email: Mapped[str] = mapped_column(String(320), default="")
    purpose: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = utc_now_column()
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)


class TokenPurpose(StrEnum):
    INVITE = "invite"
    PASSWORD_RESET = "password_reset"  # nosec B105


class OneTimeToken(Base):
    """Invitation / password-reset token. Only a SHA-256 of the token is stored."""

    __tablename__ = "one_time_tokens"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    purpose: Mapped[TokenPurpose] = mapped_column(str_enum(TokenPurpose, "token_purpose"))
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), default=None
    )
    role: Mapped[Role | None] = mapped_column(str_enum(Role, "token_role"), default=None)
    user_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), default=None
    )
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("users.id", ondelete="RESTRICT"), default=None
    )
    created_at: Mapped[datetime] = utc_now_column()
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)
