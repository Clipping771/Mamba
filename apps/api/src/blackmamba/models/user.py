import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column, validates

from blackmamba.models.base import Base, str_enum, utc_now_column


class Role(StrEnum):
    INVESTIGATOR = "investigator"
    REVIEWER = "reviewer"
    ADMIN = "admin"  # organisation admin: users + audit of their org
    PLATFORM_ADMIN = "platform_admin"  # operator: approves/suspends organisations


ADMIN_ROLES = frozenset({Role.ADMIN, Role.PLATFORM_ADMIN})
CASEWORK_ROLES = frozenset({Role.INVESTIGATOR, Role.REVIEWER})


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    # NULL only for platform admins.
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("organizations.id", ondelete="RESTRICT"), index=True, default=None
    )
    name: Mapped[str] = mapped_column(String(200))
    email: Mapped[str] = mapped_column(String(320), unique=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    role: Mapped[Role] = mapped_column(str_enum(Role, "user_role"))
    # Fernet-encrypted. Set during 2FA setup; only trusted once totp_enabled is true.
    totp_secret: Mapped[str | None] = mapped_column(String(500), default=None)
    totp_enabled: Mapped[bool] = mapped_column(Boolean, default=False)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    # Bumped on password/role/status change: invalidates all issued tokens.
    token_version: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = utc_now_column()
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), default=None)

    @validates("email")
    def _normalise_email(self, _key: str, value: str) -> str:
        return value.strip().lower()
