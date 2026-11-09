"""User accounts: login, invitations, password resets, 2FA. Every write is audited."""

import hashlib
import re
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.core.config import get_settings
from blackmamba.core.security import (
    DUMMY_PASSWORD_HASH,
    create_token,
    decrypt_field,
    hash_password,
    password_needs_rehash,
    verify_password,
    verify_totp,
)
from blackmamba.models import OneTimeToken, Organization, OrgStatus, Role, TokenPurpose, User
from blackmamba.services import audit


class AccountError(Exception):
    def __init__(self, code: str, message: str | None = None) -> None:
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def normalise_email(email: str) -> str:
    return email.strip().lower()


def hash_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:60] or "org"
    return f"{slug}-{secrets.token_hex(3)}"


@dataclass(frozen=True)
class IssuedTokens:
    access_token: str
    refresh_token: str
    expires_in: int


def issue_tokens(user: User) -> IssuedTokens:
    settings = get_settings()
    return IssuedTokens(
        access_token=create_token(user.id, "access", user.token_version),
        refresh_token=create_token(user.id, "refresh", user.token_version),
        expires_in=settings.access_token_minutes * 60,
    )


async def get_user_by_email(session: AsyncSession, email: str) -> User | None:
    return await session.scalar(select(User).where(User.email == normalise_email(email)))


async def authenticate(
    session: AsyncSession, email: str, password: str, totp_code: str | None
) -> User:
    """Raises AccountError(invalid_credentials | totp_required | invalid_totp | org_inactive)."""
    user = await get_user_by_email(session, email)
    if user is None:
        verify_password(DUMMY_PASSWORD_HASH, password)  # equalise timing
        raise AccountError("invalid_credentials", "invalid email or password")
    if not verify_password(user.password_hash, password) or not user.is_active:
        await audit.record(
            session,
            org_id=user.org_id,
            actor_id=user.id,
            action="auth.login_failed",
            target_type="user",
            target_id=user.id,
            payload={"reason": "bad_password" if user.is_active else "inactive"},
        )
        await session.commit()
        raise AccountError("invalid_credentials", "invalid email or password")
    if user.totp_enabled:
        if not totp_code:
            raise AccountError("totp_required", "enter the code from your authenticator app")
        if user.totp_secret is None or not verify_totp(decrypt_field(user.totp_secret), totp_code):
            await audit.record(
                session,
                org_id=user.org_id,
                actor_id=user.id,
                action="auth.login_failed",
                target_type="user",
                target_id=user.id,
                payload={"reason": "bad_totp"},
            )
            await session.commit()
            raise AccountError("invalid_totp", "invalid authentication code")
    if user.org_id is not None:
        org = await session.get(Organization, user.org_id)
        if org is None or org.status != OrgStatus.ACTIVE:
            raise AccountError("org_inactive", "your organisation is not active")
    if password_needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    user.last_login_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=user.id,
        action="auth.login",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return user


# ------------------------------------------------------------------ one-time tokens
async def create_one_time_token(
    session: AsyncSession,
    *,
    purpose: TokenPurpose,
    email: str,
    lifetime: timedelta,
    org_id: uuid.UUID | None = None,
    role: Role | None = None,
    user_id: uuid.UUID | None = None,
    created_by: uuid.UUID | None = None,
) -> tuple[OneTimeToken, str]:
    raw = secrets.token_urlsafe(32)
    token = OneTimeToken(
        purpose=purpose,
        token_hash=hash_token(raw),
        email=normalise_email(email),
        org_id=org_id,
        role=role,
        user_id=user_id,
        created_by=created_by,
        expires_at=datetime.now(UTC) + lifetime,
    )
    session.add(token)
    await session.flush()
    return token, raw


async def find_valid_token(session: AsyncSession, raw: str, purpose: TokenPurpose) -> OneTimeToken:
    token = await session.scalar(
        select(OneTimeToken).where(
            OneTimeToken.token_hash == hash_token(raw), OneTimeToken.purpose == purpose
        )
    )
    if token is None or token.used_at is not None or token.expires_at <= datetime.now(UTC):
        raise AccountError("invalid_token", "this link is invalid or has expired")
    return token


def invite_url(raw: str) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}/invite?token={raw}"


def reset_url(raw: str) -> str:
    return f"{get_settings().public_web_url.rstrip('/')}/reset-password?token={raw}"


async def create_invite(
    session: AsyncSession,
    *,
    org_id: uuid.UUID,
    email: str,
    role: Role,
    created_by: uuid.UUID | None,
) -> tuple[OneTimeToken, str]:
    if role == Role.PLATFORM_ADMIN:
        raise AccountError("invalid_role", "cannot invite platform admins")
    if await get_user_by_email(session, email) is not None:
        raise AccountError("email_taken", "a user with this email already exists")
    token, raw = await create_one_time_token(
        session,
        purpose=TokenPurpose.INVITE,
        email=email,
        lifetime=timedelta(days=get_settings().invite_valid_days),
        org_id=org_id,
        role=role,
        created_by=created_by,
    )
    await audit.record(
        session,
        org_id=org_id,
        actor_id=created_by,
        action="user.invite",
        target_type="invite",
        target_id=token.id,
        payload={"role": role.value},
    )
    return token, raw


async def accept_invite(session: AsyncSession, raw: str, name: str, password: str) -> User:
    token = await find_valid_token(session, raw, TokenPurpose.INVITE)
    if token.org_id is None or token.role is None:
        raise AccountError("invalid_token", "this link is invalid or has expired")
    if await get_user_by_email(session, token.email) is not None:
        raise AccountError("email_taken", "a user with this email already exists")
    user = User(
        org_id=token.org_id,
        name=name.strip(),
        email=token.email,
        password_hash=hash_password(password),
        role=token.role,
    )
    session.add(user)
    token.used_at = datetime.now(UTC)
    await session.flush()
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=user.id,
        action="user.create",
        target_type="user",
        target_id=user.id,
        payload={"role": user.role.value, "via": "invite", "invite_id": str(token.id)},
    )
    await session.commit()
    return user


async def create_password_reset(
    session: AsyncSession, user: User, created_by: uuid.UUID | None
) -> tuple[OneTimeToken, str]:
    token, raw = await create_one_time_token(
        session,
        purpose=TokenPurpose.PASSWORD_RESET,
        email=user.email,
        lifetime=timedelta(minutes=get_settings().password_reset_valid_minutes),
        org_id=user.org_id,
        user_id=user.id,
        created_by=created_by,
    )
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=created_by,
        action="user.password_reset_requested",
        target_type="user",
        target_id=user.id,
    )
    return token, raw


async def set_password(
    session: AsyncSession, user: User, password: str, actor_id: uuid.UUID | None, action: str
) -> None:
    user.password_hash = hash_password(password)
    user.token_version += 1  # log out everywhere
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=actor_id,
        action=action,
        target_type="user",
        target_id=user.id,
    )


async def confirm_password_reset(session: AsyncSession, raw: str, password: str) -> User:
    token = await find_valid_token(session, raw, TokenPurpose.PASSWORD_RESET)
    user = await session.get(User, token.user_id) if token.user_id else None
    if user is None or not user.is_active:
        raise AccountError("invalid_token", "this link is invalid or has expired")
    token.used_at = datetime.now(UTC)
    await set_password(session, user, password, user.id, "user.password_reset")
    await session.commit()
    return user
