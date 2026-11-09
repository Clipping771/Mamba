"""FR-2 (cases), FR-3 (immutable evidence), FR-5 (integrity verification)."""

import hashlib
from dataclasses import dataclass

import pytest
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.models import AuditLog, Evidence, Organization, Role, User
from blackmamba.services import audit
from blackmamba.services.storage import MemoryStorage, get_storage
from tests.factories import auth, make_org, make_user

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 64


@dataclass
class Team:
    org: Organization
    lead: User
    other: User
    reviewer: User


@pytest.fixture
async def team(session: AsyncSession) -> Team:
    org = await make_org(session)
    return Team(
        org=org,
        lead=await make_user(session, org, Role.INVESTIGATOR, name="Lead"),
        other=await make_user(session, org, Role.INVESTIGATOR, name="Other"),
        reviewer=await make_user(session, org, Role.REVIEWER, name="Rev"),
    )


async def _case(client: AsyncClient, user: User, **overrides: str) -> dict:  # type: ignore[type-arg]
    body = {"title": "Fake courier job ads", "category": "job_scam", "description": "x"}
    body.update(overrides)
    response = await client.post("/cases", headers=auth(user), json=body)
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


async def _upload(client: AsyncClient, user: User, case_id: str, data: bytes = PNG) -> dict:  # type: ignore[type-arg]
    response = await client.post(
        f"/cases/{case_id}/evidence/file",
        headers=auth(user),
        files={"file": ("ad.png", data, "image/png")},
        data={"type": "screenshot", "title": "Job ad", "source_url": "https://scam.example/job"},
    )
    assert response.status_code == 201, response.text
    return response.json()  # type: ignore[no-any-return]


# ------------------------------------------------------------------ cases
async def test_create_and_list_cases(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    assert case["status"] == "open"
    assert case["lead_id"] == str(team.lead.id)
    assert case["can_edit"] is True

    listing = await client.get("/cases", headers=auth(team.other), params={"status": "open"})
    assert listing.json()["total"] == 1
    assert (
        await client.get("/cases", headers=auth(team.other), params={"status": "closed"})
    ).json()["total"] == 0


async def test_case_status_flow_and_invalid_transition(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    url = f"/cases/{case['id']}/transition"

    invalid = await client.post(url, headers=auth(team.lead), json={"status": "closed"})
    assert invalid.status_code == 409
    assert invalid.json()["detail"]["code"] == "invalid_transition"

    for target in ["investigating", "review", "closed"]:
        response = await client.post(url, headers=auth(team.lead), json={"status": target})
        assert response.status_code == 200, response.text
        assert response.json()["status"] == target

    # Only a reviewer may reopen.
    assert (
        await client.post(url, headers=auth(team.lead), json={"status": "open"})
    ).status_code == 403
    reopened = await client.post(url, headers=auth(team.reviewer), json={"status": "open"})
    assert reopened.json()["status"] == "open"


async def test_case_changes_are_audited(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    case = await _case(client, team.lead)
    await client.patch(
        f"/cases/{case['id']}", headers=auth(team.lead), json={"title": "New title!"}
    )
    await client.post(
        f"/cases/{case['id']}/transition", headers=auth(team.lead), json={"status": "investigating"}
    )

    actions = (await session.scalars(select(AuditLog.action).order_by(AuditLog.id))).all()
    assert actions == ["case.create", "case.update", "case.transition"]
    assert (await audit.verify_chain(session, team.org.id)).ok


async def test_non_lead_investigator_cannot_edit(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    response = await client.patch(
        f"/cases/{case['id']}", headers=auth(team.other), json={"title": "Hijacked"}
    )
    assert response.status_code == 403
    # ...but a reviewer can.
    ok = await client.patch(
        f"/cases/{case['id']}", headers=auth(team.reviewer), json={"title": "Renamed"}
    )
    assert ok.status_code == 200


async def test_cases_are_isolated_between_orgs(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    case = await _case(client, team.lead)
    other_org = await make_org(session, "Elsewhere")
    outsider = await make_user(session, other_org, Role.REVIEWER)

    assert (await client.get(f"/cases/{case['id']}", headers=auth(outsider))).status_code == 404
    assert (await client.get("/cases", headers=auth(outsider))).json()["total"] == 0
    evidence = await _upload(client, team.lead, case["id"])
    assert (
        await client.get(f"/evidence/{evidence['id']}", headers=auth(outsider))
    ).status_code == 404


async def test_admin_role_has_no_case_access(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    admin = await make_user(session, team.org, Role.ADMIN)
    assert (await client.get("/cases", headers=auth(admin))).status_code == 403


# ------------------------------------------------------------------ evidence
async def test_upload_records_integrity_metadata(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)

    evidence = await _upload(client, team.lead, case["id"])

    assert evidence["sha256"] == hashlib.sha256(PNG).hexdigest()
    assert evidence["size"] == len(PNG)
    assert evidence["mime"] == "image/png"
    assert evidence["captured_by"] == str(team.lead.id)
    assert evidence["captured_at"].endswith(("Z", "+00:00"))


async def test_verify_detects_tampering(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    case = await _case(client, team.lead)
    evidence = await _upload(client, team.lead, case["id"])
    url = f"/evidence/{evidence['id']}/verify"

    assert (await client.get(url, headers=auth(team.lead))).json()["match"] is True

    storage = get_storage()
    assert isinstance(storage, MemoryStorage)
    row = await session.get(Evidence, evidence["id"])
    assert row is not None and row.storage_key is not None
    storage.objects[row.storage_key] = (PNG + b"tampered", "image/png")

    result = (await client.get(url, headers=auth(team.lead))).json()
    assert result["match"] is False
    assert result["expected"] == evidence["sha256"]
    download = await client.get(f"/evidence/{evidence['id']}/content", headers=auth(team.lead))
    assert download.status_code == 409
    assert download.json()["detail"]["code"] == "integrity_failure"
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "evidence.integrity_failure" in actions


async def test_download_is_hash_checked_attachment(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    evidence = await _upload(client, team.lead, case["id"])

    response = await client.get(f"/evidence/{evidence['id']}/content", headers=auth(team.lead))

    assert response.status_code == 200
    assert response.content == PNG
    assert response.headers["content-disposition"].startswith("attachment")
    assert "sandbox" in response.headers["content-security-policy"]
    assert response.headers["x-content-sha256"] == evidence["sha256"]


async def test_evidence_has_no_update_or_delete_api(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    evidence = await _upload(client, team.lead, case["id"])
    url = f"/evidence/{evidence['id']}"

    assert (await client.delete(url, headers=auth(team.lead))).status_code == 405
    assert (
        await client.patch(url, headers=auth(team.lead), json={"title": "x"})
    ).status_code == 405
    assert (await client.put(url, headers=auth(team.lead), json={"title": "x"})).status_code == 405


async def test_exclusion_requires_reason_and_is_audited(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    case = await _case(client, team.lead)
    evidence = await _upload(client, team.lead, case["id"])
    url = f"/evidence/{evidence['id']}/exclude"

    assert (await client.post(url, headers=auth(team.lead), json={})).status_code == 422
    excluded = await client.post(url, headers=auth(team.lead), json={"reason": "Duplicate capture"})
    assert excluded.status_code == 200
    assert excluded.json()["excluded"] is True
    assert excluded.json()["sha256"] == evidence["sha256"]
    again = await client.post(url, headers=auth(team.lead), json={"reason": "Duplicate capture"})
    assert again.status_code == 409
    assert "evidence.exclude" in (await session.scalars(select(AuditLog.action))).all()


@pytest.mark.parametrize(
    "statement",
    [
        "UPDATE evidence SET sha256 = 'f00'",
        "UPDATE evidence SET title = 'x'",
        "DELETE FROM evidence",
    ],
)
async def test_database_enforces_evidence_immutability(
    client: AsyncClient, team: Team, session: AsyncSession, statement: str
) -> None:
    case = await _case(client, team.lead)
    await _upload(client, team.lead, case["id"])

    with pytest.raises(DBAPIError, match="evidence"):
        await session.execute(text(statement))
    await session.rollback()


async def test_url_and_note_evidence(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    url_ev = await client.post(
        f"/cases/{case['id']}/evidence/url",
        headers=auth(team.lead),
        json={"url": "https://scam.example/pay", "title": "Payment page"},
    )
    note_ev = await client.post(
        f"/cases/{case['id']}/evidence/note",
        headers=auth(team.lead),
        json={"title": "Call log", "body": "Victim received 3 calls on 2026-11-01."},
    )
    assert url_ev.status_code == note_ev.status_code == 201
    assert url_ev.json()["sha256"] is None
    assert (
        note_ev.json()["sha256"]
        == hashlib.sha256(b"Victim received 3 calls on 2026-11-01.").hexdigest()
    )
    verify_url = await client.get(
        f"/evidence/{url_ev.json()['id']}/verify", headers=auth(team.lead)
    )
    assert verify_url.status_code == 409


async def test_closed_case_rejects_new_evidence(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    for target in ["investigating", "review", "closed"]:
        await client.post(
            f"/cases/{case['id']}/transition", headers=auth(team.lead), json={"status": target}
        )

    response = await client.post(
        f"/cases/{case['id']}/evidence/note",
        headers=auth(team.lead),
        json={"title": "Late", "body": "late note"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "case_closed"


async def test_case_activity_shows_custody(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    evidence = await _upload(client, team.lead, case["id"])
    await client.get(f"/evidence/{evidence['id']}/verify", headers=auth(team.reviewer))

    activity = (await client.get(f"/cases/{case['id']}/activity", headers=auth(team.other))).json()

    assert [a["action"] for a in activity] == ["evidence.verify", "evidence.capture", "case.create"]
    assert activity[0]["actor_name"] == "Rev"


async def test_human_notes(client: AsyncClient, team: Team) -> None:
    case = await _case(client, team.lead)
    created = await client.post(
        f"/cases/{case['id']}/notes", headers=auth(team.lead), json={"body": "Check WHOIS later"}
    )
    assert created.status_code == 201
    assert created.json()["is_ai_draft"] is False
    assert created.json()["label"] is None
