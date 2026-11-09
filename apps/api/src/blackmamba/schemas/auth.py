import uuid
from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, EmailStr, Field

from blackmamba.models import Role
from blackmamba.schemas.common import ORMModel

Password = Annotated[str, Field(min_length=12, max_length=256)]


class LoginRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=1, max_length=256)
    totp_code: str | None = Field(default=None, max_length=10)


class RefreshRequest(BaseModel):
    refresh_token: str


class TokenPair(BaseModel):
    access_token: str
    refresh_token: str
    token_type: Literal["bearer"] = "bearer"
    expires_in: int


class UserOut(ORMModel):
    id: uuid.UUID
    org_id: uuid.UUID | None
    name: str
    email: str
    role: Role
    totp_enabled: bool
    is_active: bool
    created_at: datetime
    last_login_at: datetime | None


class MeOut(UserOut):
    org_name: str | None = None
    requires_2fa_setup: bool = False


class TotpSetupOut(BaseModel):
    secret: str
    otpauth_uri: str


class TotpCode(BaseModel):
    code: str = Field(min_length=6, max_length=10)


class ChangePasswordRequest(BaseModel):
    current_password: str = Field(max_length=256)
    new_password: Password


class InviteInspectRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)


class InviteInspectOut(BaseModel):
    email: str
    role: Role
    org_name: str | None


class AcceptInviteRequest(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    name: str = Field(min_length=1, max_length=200)
    password: Password


class PasswordResetRequest(BaseModel):
    email: EmailStr


class PasswordResetConfirm(BaseModel):
    token: str = Field(min_length=10, max_length=200)
    password: Password
