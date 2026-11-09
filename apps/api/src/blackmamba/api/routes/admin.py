"""Organisation administration: users, invitations, audit log (admin role, 2FA required)."""

import uuid
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Query
from sqlalchemy import func, select

from blackmamba.api.deps import (
    OrgAdminUser,
    SessionDep,
    conflict,
    forbidden,
    not_found,
    org_id_of,
    unprocessable,
)
from blackmamba.models import AuditLog, OneTimeToken, Role, TokenPurpose, User
from blackmamba.schemas.admin import (
    AuditEntryOut,
    ChainVerificationOut,
    InviteCreate,
    InviteCreated,
    InviteOut,
    LinkOut,
    UserUpdate,
)
from blackmamba.schemas.auth import UserOut
from blackmamba.schemas.common import Page
from blackmamba.services import accounts, audit
from blackmamba.services.accounts import AccountError
from blackmamba.services.email import send_email

router = APIRouter(prefix="/admin", tags=["admin"])


def _invite_out(token: OneTimeToken) -> InviteOut:
    return InviteOut(
        id=token.id,
        email=token.email,
        role=token.role,
        expires_at=token.expires_at,
        used_at=token.used_at,
        created_at=token.created_at,
    )


async def _org_user(session: SessionDep, admin: User, user_id: uuid.UUID) -> User:
    user = await session.get(User, user_id)
    if user is None or user.org_id != org_id_of(admin):
        raise not_found("user")
    return user


@router.get("/users", response_model=list[UserOut])
async def list_users(admin: OrgAdminUser, session: SessionDep) -> list[User]:
    rows = await session.scalars(
        select(User).where(User.org_id == org_id_of(admin)).order_by(User.created_at)
    )
    return list(rows)


@router.patch("/users/{user_id}", response_model=UserOut)
async def update_user(
    user_id: uuid.UUID, body: UserUpdate, admin: OrgAdminUser, session: SessionDep
) -> User:
    user = await _org_user(session, admin, user_id)
    changes: dict[str, object] = {}
    if user.id == admin.id and (body.role is not None or body.is_active is False):
        raise forbidden("self_lockout", "you cannot change your own role or deactivate yourself")
    if body.role == Role.PLATFORM_ADMIN:
        raise unprocessable("invalid_role", "cannot grant platform admin")
    if body.name is not None and body.name != user.name:
        changes["name"] = body.name
        user.name = body.name
    if body.role is not None and body.role != user.role:
        changes["role"] = {"from": user.role.value, "to": body.role.value}
        user.role = body.role
        user.token_version += 1
    if body.is_active is not None and body.is_active != user.is_active:
        changes["is_active"] = body.is_active
        user.is_active = body.is_active
        user.token_version += 1
    if changes:
        await audit.record(
            session,
            org_id=user.org_id,
            actor_id=admin.id,
            action="user.update",
            target_type="user",
            target_id=user.id,
            payload=changes,
        )
        await session.commit()
    return user


@router.post("/users/{user_id}/password-reset", response_model=LinkOut)
async def admin_password_reset(
    user_id: uuid.UUID, admin: OrgAdminUser, session: SessionDep
) -> LinkOut:
    user = await _org_user(session, admin, user_id)
    token, raw = await accounts.create_password_reset(session, user, created_by=admin.id)
    await session.commit()
    url = accounts.reset_url(raw)
    emailed = await send_email(
        user.email, "BLACK MAMBA password reset", f"Reset your password here:\n\n{url}"
    )
    return LinkOut(url=url, expires_at=token.expires_at, emailed=emailed)


@router.post("/users/{user_id}/reset-2fa", response_model=UserOut)
async def admin_reset_2fa(user_id: uuid.UUID, admin: OrgAdminUser, session: SessionDep) -> User:
    """For a lost authenticator. The user must set 2FA up again (admins before acting)."""
    user = await _org_user(session, admin, user_id)
    if user.id == admin.id:
        raise forbidden("self_lockout", "ask another admin to reset your 2FA")
    user.totp_enabled = False
    user.totp_secret = None
    user.token_version += 1
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=admin.id,
        action="user.2fa_reset",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return user


# ------------------------------------------------------------------ invitations
@router.get("/invitations", response_model=list[InviteOut])
async def list_invitations(admin: OrgAdminUser, session: SessionDep) -> list[InviteOut]:
    rows = await session.scalars(
        select(OneTimeToken)
        .where(
            OneTimeToken.org_id == org_id_of(admin),
            OneTimeToken.purpose == TokenPurpose.INVITE,
            OneTimeToken.used_at.is_(None),
            OneTimeToken.expires_at > datetime.now(UTC),
        )
        .order_by(OneTimeToken.created_at.desc())
    )
    return [_invite_out(t) for t in rows]


@router.post("/invitations", response_model=InviteCreated, status_code=201)
async def create_invitation(
    body: InviteCreate, admin: OrgAdminUser, session: SessionDep
) -> InviteCreated:
    try:
        token, raw = await accounts.create_invite(
            session, org_id=org_id_of(admin), email=body.email, role=body.role, created_by=admin.id
        )
    except AccountError as exc:
        raise conflict(exc.code, exc.message) from exc
    await session.commit()
    url = accounts.invite_url(raw)
    emailed = await send_email(
        token.email,
        "You're invited to BLACK MAMBA",
        f"{admin.name} invited you to join their investigation team as {body.role.value}.\n\n"
        f"Accept the invitation here:\n\n{url}\n\nThis link expires on "
        f"{token.expires_at:%Y-%m-%d %H:%M} UTC.",
    )
    return InviteCreated(invite=_invite_out(token), invite_url=url, emailed=emailed)


@router.post("/invitations/{invite_id}/revoke", response_model=InviteOut)
async def revoke_invitation(
    invite_id: uuid.UUID, admin: OrgAdminUser, session: SessionDep
) -> InviteOut:
    token = await session.get(OneTimeToken, invite_id)
    if token is None or token.org_id != org_id_of(admin) or token.purpose != TokenPurpose.INVITE:
        raise not_found("invitation")
    if token.used_at is not None:
        raise conflict("invite_used", "invitation already used")
    token.expires_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=token.org_id,
        actor_id=admin.id,
        action="user.invite_revoked",
        target_type="invite",
        target_id=token.id,
    )
    await session.commit()
    return _invite_out(token)


# ------------------------------------------------------------------ audit log (FR-9)
@router.get("/audit", response_model=Page[AuditEntryOut])
async def list_audit(
    admin: OrgAdminUser,
    session: SessionDep,
    limit: Annotated[int, Query(ge=1, le=500)] = 100,
    offset: Annotated[int, Query(ge=0)] = 0,
    action: str | None = None,
) -> Page[AuditEntryOut]:
    org_id = org_id_of(admin)
    query = select(AuditLog).where(AuditLog.org_id == org_id)
    if action:
        query = query.where(AuditLog.action == action)
    total = await session.scalar(select(func.count()).select_from(query.subquery())) or 0
    rows = await session.scalars(query.order_by(AuditLog.id.desc()).limit(limit).offset(offset))
    return Page(
        items=[AuditEntryOut.model_validate(r) for r in rows],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/audit/verify", response_model=ChainVerificationOut)
async def verify_audit(admin: OrgAdminUser, session: SessionDep) -> ChainVerificationOut:
    result = await audit.verify_chain(session, org_id_of(admin))
    return ChainVerificationOut(
        ok=result.ok,
        entries_checked=result.entries_checked,
        first_bad_id=result.first_bad_id,
        reason=result.reason,
    )
