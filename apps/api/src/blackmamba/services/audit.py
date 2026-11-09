"""Append-only, hash-chained audit log (FR-9 / NFR-2).

hash = sha256(prev_hash || canonical_json({org_id, actor_id, action, target_type, target_id,
payload, ts})). Each organisation has its own chain; org_id NULL is the platform chain.
Genesis prev_hash is 64 zeros. Writers serialise per chain with a transaction-scoped
advisory lock, so the chain stays linear under concurrency.
"""

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.models import AuditLog

GENESIS_HASH = "0" * 64


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _normalise_payload(payload: dict[str, Any] | None) -> dict[str, Any]:
    # Round-trip through JSON so what we hash is exactly what JSONB will give back.
    result: dict[str, Any] = json.loads(json.dumps(payload or {}, default=str))
    return result


def _entry(
    *,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None,
    target_id: str | None,
    payload: dict[str, Any],
    ts: datetime,
) -> dict[str, Any]:
    return {
        "org_id": str(org_id) if org_id else None,
        "actor_id": str(actor_id) if actor_id else None,
        "action": action,
        "target_type": target_type,
        "target_id": target_id,
        "payload": payload,
        "ts": ts.astimezone(UTC).isoformat(),
    }


def compute_hash(prev_hash: str, entry: dict[str, Any]) -> str:
    return hashlib.sha256((prev_hash + canonical_json(entry)).encode("utf-8")).hexdigest()


def _lock_key(org_id: uuid.UUID | None) -> int:
    digest = hashlib.sha256(b"bm-audit:" + (org_id.bytes if org_id else b"platform")).digest()
    return int.from_bytes(digest[:8], "big", signed=True)


def _chain_filter(org_id: uuid.UUID | None) -> Any:
    return AuditLog.org_id.is_(None) if org_id is None else AuditLog.org_id == org_id


async def record(
    session: AsyncSession,
    *,
    org_id: uuid.UUID | None,
    actor_id: uuid.UUID | None,
    action: str,
    target_type: str | None = None,
    target_id: uuid.UUID | str | None = None,
    payload: dict[str, Any] | None = None,
) -> AuditLog:
    """Append an entry in the caller's transaction (commit it together with the change)."""
    await session.execute(text("SELECT pg_advisory_xact_lock(:key)"), {"key": _lock_key(org_id)})
    prev_hash = (
        await session.scalar(
            select(AuditLog.hash).where(_chain_filter(org_id)).order_by(AuditLog.id.desc()).limit(1)
        )
        or GENESIS_HASH
    )
    ts = datetime.now(UTC)
    clean_payload = _normalise_payload(payload)
    target = str(target_id) if target_id is not None else None
    entry_hash = compute_hash(
        prev_hash,
        _entry(
            org_id=org_id,
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=target,
            payload=clean_payload,
            ts=ts,
        ),
    )
    row = AuditLog(
        org_id=org_id,
        actor_id=actor_id,
        action=action,
        target_type=target_type,
        target_id=target,
        payload=clean_payload,
        ts=ts,
        prev_hash=prev_hash,
        hash=entry_hash,
    )
    session.add(row)
    await session.flush()
    return row


@dataclass(frozen=True)
class ChainVerification:
    ok: bool
    entries_checked: int
    first_bad_id: int | None = None
    reason: str | None = None


async def verify_chain(
    session: AsyncSession, org_id: uuid.UUID | None, batch_size: int = 1000
) -> ChainVerification:
    """Recompute every hash in the chain; detect edits, deletions and re-ordering."""
    prev_hash = GENESIS_HASH
    checked = 0
    last_id = 0
    while True:
        rows = (
            await session.scalars(
                select(AuditLog)
                .where(_chain_filter(org_id), AuditLog.id > last_id)
                .order_by(AuditLog.id)
                .limit(batch_size)
            )
        ).all()
        if not rows:
            return ChainVerification(ok=True, entries_checked=checked)
        for row in rows:
            if row.prev_hash != prev_hash:
                return ChainVerification(False, checked, row.id, "broken link (prev_hash)")
            expected = compute_hash(
                prev_hash,
                _entry(
                    org_id=row.org_id,
                    actor_id=row.actor_id,
                    action=row.action,
                    target_type=row.target_type,
                    target_id=row.target_id,
                    payload=row.payload,
                    ts=row.ts,
                ),
            )
            if expected != row.hash:
                return ChainVerification(False, checked, row.id, "hash mismatch (row modified)")
            prev_hash = row.hash
            checked += 1
            last_id = row.id


async def count_entries(session: AsyncSession, org_id: uuid.UUID | None) -> int:
    return int(
        await session.scalar(
            select(func.count()).select_from(AuditLog).where(_chain_filter(org_id))
        )
        or 0
    )
