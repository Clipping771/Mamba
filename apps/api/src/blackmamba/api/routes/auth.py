"""Authentication (FR-1): login with optional TOTP, refresh, 2FA, invites, password resets."""

from typing import Annotated

from fastapi import APIRouter, Depends, Request, status

from blackmamba.api.deps import (
    CurrentUser,
    SessionDep,
    client_ip,
    conflict,
    forbidden,
    http_error,
    unauthorized,
    unprocessable,
)
from blackmamba.core.config import get_settings
from blackmamba.core.security import (
    TokenError,
    decode_token,
    decrypt_field,
    encrypt_field,
    new_totp_secret,
    totp_uri,
    verify_password,
    verify_totp,
)
from blackmamba.models import ADMIN_ROLES, Organization, TokenPurpose, User
from blackmamba.schemas.auth import (
    AcceptInviteRequest,
    ChangePasswordRequest,
    InviteInspectOut,
    InviteInspectRequest,
    LoginRequest,
    MeOut,
    PasswordResetConfirm,
    PasswordResetRequest,
    RefreshRequest,
    TokenPair,
    TotpCode,
    TotpSetupOut,
    UserOut,
)
from blackmamba.schemas.common import Message
from blackmamba.services import accounts, audit
from blackmamba.services.accounts import AccountError
from blackmamba.services.email import send_email
from blackmamba.services.rate_limit import RateLimiter, get_rate_limiter

router = APIRouter(prefix="/auth", tags=["auth"])

RateLimiterDep = Annotated[RateLimiter, Depends(get_rate_limiter)]


def _tokens(user: User) -> TokenPair:
    issued = accounts.issue_tokens(user)
    return TokenPair(
        access_token=issued.access_token,
        refresh_token=issued.refresh_token,
        expires_in=issued.expires_in,
    )


@router.post("/login", response_model=TokenPair)
async def login(
    body: LoginRequest, request: Request, session: SessionDep, limiter: RateLimiterDep
) -> TokenPair:
    settings = get_settings()
    ip = client_ip(request)
    email = accounts.normalise_email(body.email)
    window = settings.login_rate_window_seconds
    if not await limiter.hit(f"login:ip:{ip}", settings.login_rate_limit_ip, window) or not (
        await limiter.hit(f"login:{ip}:{email}", settings.login_rate_limit, window)
    ):
        raise http_error(
            status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "too many attempts, try later"
        )
    try:
        user = await accounts.authenticate(session, email, body.password, body.totp_code)
    except AccountError as exc:
        if exc.code == "org_inactive":
            raise forbidden(exc.code, exc.message) from exc
        raise unauthorized(exc.code, exc.message) from exc
    await limiter.reset(f"login:{ip}:{email}")
    return _tokens(user)


@router.post("/refresh", response_model=TokenPair)
async def refresh(body: RefreshRequest, session: SessionDep) -> TokenPair:
    try:
        claims = decode_token(body.refresh_token, "refresh")
    except TokenError as exc:
        raise unauthorized("invalid_token", "invalid or expired token") from exc
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.version:
        raise unauthorized("invalid_token", "invalid or expired token")
    if user.org_id is not None:
        org = await session.get(Organization, user.org_id)
        if org is None or org.status != "active":
            raise forbidden("org_inactive", "your organisation is not active")
    return _tokens(user)


@router.get("/me", response_model=MeOut)
async def me(user: CurrentUser, session: SessionDep) -> MeOut:
    org = await session.get(Organization, user.org_id) if user.org_id else None
    return MeOut(
        **UserOut.model_validate(user).model_dump(),
        org_name=org.name if org else None,
        requires_2fa_setup=user.role in ADMIN_ROLES and not user.totp_enabled,
    )


# ------------------------------------------------------------------ 2FA
@router.post("/2fa/setup", response_model=TotpSetupOut)
async def totp_setup(user: CurrentUser, session: SessionDep) -> TotpSetupOut:
    if user.totp_enabled:
        raise conflict("totp_already_enabled", "2FA is already enabled")
    secret = new_totp_secret()
    user.totp_secret = encrypt_field(secret)
    await session.commit()
    return TotpSetupOut(secret=secret, otpauth_uri=totp_uri(secret, user.email))


@router.post("/2fa/enable", response_model=UserOut)
async def totp_enable(body: TotpCode, user: CurrentUser, session: SessionDep) -> User:
    if user.totp_enabled:
        raise conflict("totp_already_enabled", "2FA is already enabled")
    if user.totp_secret is None:
        raise conflict("totp_not_setup", "call /auth/2fa/setup first")
    if not verify_totp(decrypt_field(user.totp_secret), body.code):
        raise unprocessable("invalid_totp", "invalid authentication code")
    user.totp_enabled = True
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=user.id,
        action="user.2fa_enabled",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return user


@router.post("/2fa/disable", response_model=UserOut)
async def totp_disable(body: TotpCode, user: CurrentUser, session: SessionDep) -> User:
    if user.role in ADMIN_ROLES:
        raise forbidden("admin_requires_2fa", "administrators cannot disable 2FA")
    if not user.totp_enabled or user.totp_secret is None:
        raise conflict("totp_not_enabled", "2FA is not enabled")
    if not verify_totp(decrypt_field(user.totp_secret), body.code):
        raise unprocessable("invalid_totp", "invalid authentication code")
    user.totp_enabled = False
    user.totp_secret = None
    await audit.record(
        session,
        org_id=user.org_id,
        actor_id=user.id,
        action="user.2fa_disabled",
        target_type="user",
        target_id=user.id,
    )
    await session.commit()
    return user


# ------------------------------------------------------------------ passwords
@router.post("/change-password", response_model=TokenPair)
async def change_password(
    body: ChangePasswordRequest, user: CurrentUser, session: SessionDep
) -> TokenPair:
    if not verify_password(user.password_hash, body.current_password):
        raise unprocessable("invalid_password", "current password is incorrect")
    await accounts.set_password(session, user, body.new_password, user.id, "user.password_change")
    await session.commit()
    return _tokens(user)  # old tokens are revoked by the version bump


@router.post("/password-reset/request", response_model=Message, status_code=202)
async def password_reset_request(
    body: PasswordResetRequest, request: Request, session: SessionDep, limiter: RateLimiterDep
) -> Message:
    generic = Message(message="If the account exists, a reset link has been sent.")
    settings = get_settings()
    if not await limiter.hit(
        f"reset:{client_ip(request)}", settings.login_rate_limit, settings.login_rate_window_seconds
    ):
        return generic  # no enumeration, no spam
    user = await accounts.get_user_by_email(session, body.email)
    if user is None or not user.is_active:
        return generic
    _, raw = await accounts.create_password_reset(session, user, created_by=None)
    await session.commit()
    await send_email(
        user.email,
        "BLACK MAMBA password reset",
        f"Use this link within {settings.password_reset_valid_minutes} minutes to reset your "
        f"password:\n\n{accounts.reset_url(raw)}\n\nIf you did not ask for this, ignore it.",
    )
    return generic


@router.post("/password-reset/confirm", response_model=Message)
async def password_reset_confirm(body: PasswordResetConfirm, session: SessionDep) -> Message:
    try:
        await accounts.confirm_password_reset(session, body.token, body.password)
    except AccountError as exc:
        raise unprocessable(exc.code, exc.message) from exc
    return Message(message="Password updated. You can now sign in.")


# ------------------------------------------------------------------ invitations
@router.post("/invite/inspect", response_model=InviteInspectOut)
async def invite_inspect(body: InviteInspectRequest, session: SessionDep) -> InviteInspectOut:
    try:
        token = await accounts.find_valid_token(session, body.token, TokenPurpose.INVITE)
    except AccountError as exc:
        raise unprocessable(exc.code, exc.message) from exc
    org = await session.get(Organization, token.org_id) if token.org_id else None
    if token.role is None:
        raise unprocessable("invalid_token", "this link is invalid or has expired")
    return InviteInspectOut(email=token.email, role=token.role, org_name=org.name if org else None)


@router.post("/invite/accept", response_model=UserOut, status_code=201)
async def invite_accept(body: AcceptInviteRequest, session: SessionDep) -> User:
    try:
        return await accounts.accept_invite(session, body.token, body.name, body.password)
    except AccountError as exc:
        raise unprocessable(exc.code, exc.message) from exc
