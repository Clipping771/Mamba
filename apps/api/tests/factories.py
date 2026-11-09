"""Test data helpers. Users are created directly; tokens are minted without the login flow."""

import pyotp
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.core.security import create_token, encrypt_field, hash_password
from blackmamba.models import Organization, OrgStatus, Role, User
from blackmamba.services import accounts

PASSWORD = "correct horse battery staple"


async def make_org(
    session: AsyncSession, name: str = "Test Org", status: OrgStatus = OrgStatus.ACTIVE
) -> Organization:
    org = Organization(name=name, slug=accounts.slugify(name), status=status)
    session.add(org)
    await session.commit()
    return org


async def make_user(
    session: AsyncSession,
    org: Organization | None,
    role: Role,
    email: str | None = None,
    *,
    totp_secret: str | None = None,
    name: str | None = None,
) -> User:
    if role in {Role.ADMIN, Role.PLATFORM_ADMIN} and totp_secret is None:
        totp_secret = pyotp.random_base32()
    user = User(
        org_id=org.id if org else None,
        name=name or f"{role.value} user",
        email=email or f"{role.value}-{pyotp.random_base32()[:6].lower()}@example.org",
        password_hash=hash_password(PASSWORD),
        role=role,
        totp_secret=encrypt_field(totp_secret) if totp_secret else None,
        totp_enabled=totp_secret is not None,
    )
    session.add(user)
    await session.commit()
    return user


def auth(user: User) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_token(user.id, 'access', user.token_version)}"}
