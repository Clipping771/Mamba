import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, EmailStr, Field

from blackmamba.models import OrgStatus, Role
from blackmamba.schemas.common import ORMModel


class InviteCreate(BaseModel):
    email: EmailStr
    role: Role


class InviteOut(BaseModel):
    id: uuid.UUID
    email: str
    role: Role | None
    expires_at: datetime
    used_at: datetime | None
    created_at: datetime


class InviteCreated(BaseModel):
    invite: InviteOut
    # Shown once. Share it securely if email is not configured.
    invite_url: str
    emailed: bool


class LinkOut(BaseModel):
    url: str
    expires_at: datetime
    emailed: bool


class UserUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    role: Role | None = None
    is_active: bool | None = None


class AuditEntryOut(ORMModel):
    id: int
    org_id: uuid.UUID | None
    actor_id: uuid.UUID | None
    action: str
    target_type: str | None
    target_id: str | None
    payload: dict[str, Any]
    ts: datetime
    prev_hash: str
    hash: str


class ChainVerificationOut(BaseModel):
    ok: bool
    entries_checked: int
    first_bad_id: int | None
    reason: str | None


class OrgApplication(BaseModel):
    org_name: str = Field(min_length=2, max_length=200)
    contact_name: str = Field(min_length=1, max_length=200)
    contact_email: EmailStr
    purpose: str = Field(min_length=20, max_length=4000)


class OrgOut(ORMModel):
    id: uuid.UUID
    name: str
    slug: str
    status: OrgStatus
    contact_name: str
    contact_email: str
    purpose: str
    created_at: datetime
    reviewed_at: datetime | None


class OrgDecision(BaseModel):
    reason: str | None = Field(default=None, max_length=2000)


class OrgApproved(BaseModel):
    org: OrgOut
    admin_invite_url: str
    emailed: bool
