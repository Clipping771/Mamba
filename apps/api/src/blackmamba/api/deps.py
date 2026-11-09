"""Shared FastAPI dependencies: DB session, authentication, role checks, tenancy."""

import uuid
from collections.abc import Callable, Coroutine
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.core.db import get_session
from blackmamba.core.security import TokenError, decode_token
from blackmamba.models import ADMIN_ROLES, Organization, OrgStatus, Role, User

SessionDep = Annotated[AsyncSession, Depends(get_session)]

_bearer = HTTPBearer(auto_error=False)


def http_error(status_code: int, code: str, message: str | None = None) -> HTTPException:
    """Errors carry a stable machine-readable `code` plus a human message."""
    return HTTPException(status_code=status_code, detail={"code": code, "message": message or code})


def unauthorized(code: str = "not_authenticated", message: str | None = None) -> HTTPException:
    exc = http_error(status.HTTP_401_UNAUTHORIZED, code, message)
    exc.headers = {"WWW-Authenticate": "Bearer"}
    return exc


def forbidden(code: str = "forbidden", message: str | None = None) -> HTTPException:
    return http_error(status.HTTP_403_FORBIDDEN, code, message)


def not_found(what: str = "resource") -> HTTPException:
    return http_error(status.HTTP_404_NOT_FOUND, "not_found", f"{what} not found")


def conflict(code: str, message: str | None = None) -> HTTPException:
    return http_error(status.HTTP_409_CONFLICT, code, message)


def unprocessable(code: str, message: str | None = None) -> HTTPException:
    return http_error(status.HTTP_422_UNPROCESSABLE_ENTITY, code, message)


async def ensure_org_active(session: AsyncSession, user: User) -> None:
    if user.org_id is None:
        return
    org = await session.get(Organization, user.org_id)
    if org is None or org.status != OrgStatus.ACTIVE:
        raise forbidden("org_inactive", "your organisation is not active")


async def get_current_user(
    session: SessionDep,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
) -> User:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise unauthorized()
    try:
        claims = decode_token(credentials.credentials, "access")
    except TokenError as exc:
        raise unauthorized("invalid_token", "invalid or expired token") from exc
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active or user.token_version != claims.version:
        raise unauthorized("invalid_token", "invalid or expired token")
    await ensure_org_active(session, user)
    return user


CurrentUser = Annotated[User, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[..., Coroutine[Any, Any, User]]:
    allowed = frozenset(roles)

    async def dependency(user: CurrentUser) -> User:
        if user.role not in allowed:
            raise forbidden("insufficient_role", "your role does not allow this action")
        if user.role in ADMIN_ROLES and not user.totp_enabled:
            raise forbidden("admin_requires_2fa", "administrators must enable 2FA first")
        return user

    return dependency


# Casework = investigators and reviewers of an organisation.
CaseworkUser = Annotated[User, Depends(require_roles(Role.INVESTIGATOR, Role.REVIEWER))]
ReviewerUser = Annotated[User, Depends(require_roles(Role.REVIEWER))]
OrgAdminUser = Annotated[User, Depends(require_roles(Role.ADMIN))]
PlatformAdminUser = Annotated[User, Depends(require_roles(Role.PLATFORM_ADMIN))]


def org_id_of(user: User) -> uuid.UUID:
    if user.org_id is None:  # platform admins never reach tenant routes (role checks)
        raise forbidden("no_organisation")
    return user.org_id


def client_ip(request: Request) -> str:
    # Uvicorn runs with --proxy-headers behind Caddy, so request.client is the real client.
    return request.client.host if request.client else "unknown"
