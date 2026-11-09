"""FR-9: append-only, hash-chained audit log."""

import asyncio
import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.core.db import get_sessionmaker
from blackmamba.models import Role
from blackmamba.services import audit
from tests.factories import auth, make_org, make_user


async def _write_entries(session: AsyncSession, org_id: uuid.UUID | None, n: int) -> None:
    for i in range(n):
        await audit.record(
            session,
            org_id=org_id,
            actor_id=None,
            action="test.event",
            target_type="thing",
            target_id=str(i),
            payload={"i": i, "text": "naïve — ünïcode"},
        )
    await session.commit()


async def test_chain_verifies_and_links(session: AsyncSession) -> None:
    org = await make_org(session)
    await _write_entries(session, org.id, 5)

    result = await audit.verify_chain(session, org.id)

    assert result.ok
    assert result.entries_checked == 5


async def test_first_entry_uses_genesis_hash(session: AsyncSession) -> None:
    entry = await audit.record(session, org_id=None, actor_id=None, action="test.first")
    assert entry.prev_hash == audit.GENESIS_HASH


async def test_tampered_row_breaks_chain(session: AsyncSession) -> None:
    org = await make_org(session)
    await _write_entries(session, org.id, 4)

    # Simulate an attacker with DB access: disable the trigger and edit a row directly.
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(
        text("UPDATE audit_log SET payload = '{\"i\": 99}' WHERE target_id = '2' AND org_id = :o"),
        {"o": org.id},
    )
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    await session.commit()

    result = await audit.verify_chain(session, org.id)

    assert not result.ok
    assert result.reason == "hash mismatch (row modified)"


async def test_deleted_row_breaks_chain(session: AsyncSession) -> None:
    org = await make_org(session)
    await _write_entries(session, org.id, 4)
    await session.execute(text("ALTER TABLE audit_log DISABLE TRIGGER audit_log_append_only"))
    await session.execute(
        text("DELETE FROM audit_log WHERE target_id = '1' AND org_id = :o"), {"o": org.id}
    )
    await session.execute(text("ALTER TABLE audit_log ENABLE TRIGGER audit_log_append_only"))
    await session.commit()

    result = await audit.verify_chain(session, org.id)

    assert not result.ok
    assert result.reason == "broken link (prev_hash)"


@pytest.mark.parametrize(
    "statement", ["UPDATE audit_log SET action = 'x'", "DELETE FROM audit_log"]
)
async def test_database_rejects_update_and_delete(session: AsyncSession, statement: str) -> None:
    await _write_entries(session, None, 1)
    with pytest.raises(DBAPIError, match="append-only"):
        await session.execute(text(statement))
    await session.rollback()


async def test_chains_are_isolated_per_org(session: AsyncSession) -> None:
    org_a = await make_org(session, "A")
    org_b = await make_org(session, "B")
    await _write_entries(session, org_a.id, 3)
    await _write_entries(session, org_b.id, 2)
    await _write_entries(session, org_a.id, 1)

    a = await audit.verify_chain(session, org_a.id)
    b = await audit.verify_chain(session, org_b.id)
    assert (a.ok, a.entries_checked) == (True, 4)
    assert (b.ok, b.entries_checked) == (True, 2)


async def test_concurrent_writers_keep_chain_linear(db: None) -> None:
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as s:
        org = await make_org(s)

    async def writer(n: int) -> None:
        async with sessionmaker() as s:
            await _write_entries(s, org.id, n)

    await asyncio.gather(*(writer(5) for _ in range(4)))

    async with sessionmaker() as s:
        result = await audit.verify_chain(s, org.id)
    assert result.ok
    assert result.entries_checked == 20


async def test_admin_audit_endpoints(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    admin = await make_user(session, org, Role.ADMIN)
    await _write_entries(session, org.id, 3)

    listing = await client.get("/admin/audit", headers=auth(admin))
    verify = await client.get("/admin/audit/verify", headers=auth(admin))

    assert listing.json()["total"] == 3
    assert verify.json()["ok"] is True
    # No mutation endpoints exist for the audit log.
    assert (await client.delete("/admin/audit", headers=auth(admin))).status_code == 405
