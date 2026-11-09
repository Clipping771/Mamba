"""Operator CLI.

    blackmamba create-platform-admin --email ops@example.org --name "Ops"
    blackmamba create-org --name "Scam Watch" --admin-email lead@example.org
    blackmamba verify-audit [--org-id UUID]
    blackmamba verify-all          (every audit chain + re-hash all evidence; after restores)
    BM_SEED_PASSWORD=... blackmamba seed-demo   (development only)

Passwords are read from BM_ADMIN_PASSWORD or prompted (never passed as an argument).
"""

import argparse
import asyncio
import getpass
import os
import sys
import uuid

from sqlalchemy import select

from blackmamba.core.config import get_settings
from blackmamba.core.db import get_engine, get_sessionmaker
from blackmamba.core.security import hash_password
from blackmamba.models import Organization, OrgStatus, Role, User
from blackmamba.services import accounts, audit


def _read_password() -> str:
    password = os.environ.get("BM_ADMIN_PASSWORD") or getpass.getpass("Password: ")
    if len(password) < get_settings().min_password_length:
        sys.exit(f"password must be at least {get_settings().min_password_length} characters")
    return password


async def create_platform_admin(email: str, name: str, password: str) -> uuid.UUID:
    async with get_sessionmaker()() as session:
        if await accounts.get_user_by_email(session, email):
            sys.exit("a user with this email already exists")
        user = User(
            org_id=None,
            name=name,
            email=accounts.normalise_email(email),
            password_hash=hash_password(password),
            role=Role.PLATFORM_ADMIN,
        )
        session.add(user)
        await session.flush()
        await audit.record(
            session,
            org_id=None,
            actor_id=None,
            action="user.create",
            target_type="user",
            target_id=user.id,
            payload={"role": Role.PLATFORM_ADMIN.value, "via": "cli"},
        )
        await session.commit()
        return user.id


async def create_org(name: str, admin_email: str) -> str:
    async with get_sessionmaker()() as session:
        org = Organization(
            name=name,
            slug=accounts.slugify(name),
            status=OrgStatus.ACTIVE,
            contact_email=accounts.normalise_email(admin_email),
            purpose="created by operator CLI",
        )
        session.add(org)
        await session.flush()
        await audit.record(
            session,
            org_id=None,
            actor_id=None,
            action="org.active",
            target_type="org",
            target_id=org.id,
            payload={"via": "cli"},
        )
        _, raw = await accounts.create_invite(
            session, org_id=org.id, email=admin_email, role=Role.ADMIN, created_by=None
        )
        await session.commit()
        return accounts.invite_url(raw)


DEMO_USERS = [
    ("platform@demo.example.org", "Pat Platform", Role.PLATFORM_ADMIN),
    ("admin@demo.example.org", "Ada Admin", Role.ADMIN),
    ("lead@demo.example.org", "Lee Investigator", Role.INVESTIGATOR),
    ("reviewer@demo.example.org", "Rae Reviewer", Role.REVIEWER),
]


async def seed_demo(password: str) -> list[tuple[str, str, str | None]]:
    """Development only: one active org with one user per role. Idempotent."""
    if get_settings().app_env == "production":
        sys.exit("refusing to seed demo data in production")
    import pyotp

    from blackmamba.core.security import encrypt_field

    created: list[tuple[str, str, str | None]] = []
    async with get_sessionmaker()() as session:
        org = await session.scalar(
            select(Organization).where(Organization.slug == "demo-investigations")
        )
        if org is None:
            org = Organization(
                name="Demo Investigations",
                slug="demo-investigations",
                status=OrgStatus.ACTIVE,
                purpose="development seed data",
            )
            session.add(org)
            await session.flush()
        for email, name, role in DEMO_USERS:
            if await accounts.get_user_by_email(session, email):
                continue
            totp = pyotp.random_base32() if role in {Role.ADMIN, Role.PLATFORM_ADMIN} else None
            user = User(
                org_id=None if role == Role.PLATFORM_ADMIN else org.id,
                name=name,
                email=email,
                password_hash=hash_password(password),
                role=role,
                totp_secret=encrypt_field(totp) if totp else None,
                totp_enabled=totp is not None,
            )
            session.add(user)
            await session.flush()
            await audit.record(
                session,
                org_id=user.org_id,
                actor_id=None,
                action="user.create",
                target_type="user",
                target_id=user.id,
                payload={"role": role.value, "via": "seed-demo"},
            )
            created.append((email, role.value, totp))
        await session.commit()
    return created


async def verify_evidence() -> bool:
    """Re-hash every stored evidence object (used after restores and in periodic checks)."""
    from blackmamba.models import Evidence
    from blackmamba.services.evidence import read_and_verify
    from blackmamba.services.storage import ObjectMissingError, get_storage

    storage = get_storage()
    checked = failed = 0
    async with get_sessionmaker()() as session:
        rows = await session.scalars(select(Evidence).where(Evidence.storage_key.is_not(None)))
        for evidence in rows:
            checked += 1
            try:
                _, result = await read_and_verify(storage, evidence)
                ok = result.match
            except ObjectMissingError:
                ok = False
            if not ok:
                failed += 1
                print(f"FAIL: evidence {evidence.id} (case {evidence.case_id})")
    print(
        f"{'OK' if failed == 0 else 'FAIL'}: {checked - failed}/{checked} evidence objects intact"
    )
    return failed == 0


async def verify(org_id: uuid.UUID | None) -> bool:
    async with get_sessionmaker()() as session:
        result = await audit.verify_chain(session, org_id)
    label = f"org {org_id}" if org_id else "platform"
    if result.ok:
        print(f"OK: {label} audit chain intact ({result.entries_checked} entries)")
    else:
        print(f"FAIL: {label} chain broken at id={result.first_bad_id}: {result.reason}")
    return result.ok


async def _run(args: argparse.Namespace) -> int:
    try:
        if args.command == "create-platform-admin":
            user_id = await create_platform_admin(args.email, args.name, _read_password())
            print(f"Created platform admin {user_id}. Sign in and enable 2FA.")
        elif args.command == "create-org":
            url = await create_org(args.name, args.admin_email)
            print(f"Organisation created. Send this one-time admin invite securely:\n{url}")
        elif args.command == "verify-audit":
            return 0 if await verify(args.org_id) else 1
        elif args.command == "verify-all":
            async with get_sessionmaker()() as session:
                org_ids: list[uuid.UUID | None] = [
                    None,
                    *await session.scalars(select(Organization.id)),
                ]
            chains_ok = all([await verify(org_id) for org_id in org_ids])
            return 0 if chains_ok and await verify_evidence() else 1
        elif args.command == "seed-demo":
            password = os.environ.get("BM_SEED_PASSWORD", "")
            if len(password) < get_settings().min_password_length:
                sys.exit("set BM_SEED_PASSWORD (>= 12 characters)")
            for email, role, totp in await seed_demo(password):
                extra = f"  TOTP secret: {totp}" if totp else ""
                print(f"created {role:<15} {email}{extra}")
            print("Demo data ready (existing users were left unchanged).")
        return 0
    finally:
        await get_engine().dispose()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="blackmamba", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("create-platform-admin", help="bootstrap the first operator account")
    p.add_argument("--email", required=True)
    p.add_argument("--name", required=True)
    p = sub.add_parser("create-org", help="create an active organisation + admin invite")
    p.add_argument("--name", required=True)
    p.add_argument("--admin-email", required=True)
    p = sub.add_parser("verify-audit", help="verify an audit hash chain")
    p.add_argument("--org-id", type=uuid.UUID, default=None)
    sub.add_parser("verify-all", help="verify every audit chain and re-hash all evidence")
    sub.add_parser("seed-demo", help="DEV ONLY: demo org + one user per role (BM_SEED_PASSWORD)")
    return asyncio.run(_run(parser.parse_args(argv)))


if __name__ == "__main__":
    raise SystemExit(main())
