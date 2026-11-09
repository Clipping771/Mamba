"""FR-6/FR-7 (findings + review), FR-8 (reports), FR-10 (ARCHIVIST)."""

from dataclasses import dataclass

import pytest
from fastapi import FastAPI
from httpx import AsyncClient
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.agents.archivist import SYSTEM_PROMPT
from blackmamba.agents.llm import FakeLLM, get_llm
from blackmamba.core.db import get_engine
from blackmamba.models import AI_DRAFT_LABEL, AuditLog, Note, Organization, Role, User
from blackmamba.services import report
from tests.factories import auth, make_org, make_user


@dataclass
class Team:
    org: Organization
    author: User
    reviewer: User
    reviewer2: User
    case_id: str
    evidence_ids: list[str]


@pytest.fixture
async def team(client: AsyncClient, session: AsyncSession) -> Team:
    org = await make_org(session)
    author = await make_user(session, org, Role.INVESTIGATOR, name="Ivy Investigator")
    reviewer = await make_user(session, org, Role.REVIEWER, name="Rae Reviewer")
    reviewer2 = await make_user(session, org, Role.REVIEWER, name="Rob Reviewer")
    case = (
        await client.post(
            "/cases",
            headers=auth(author),
            json={
                "title": "Fake parcel fee SMS",
                "category": "phishing",
                "description": "SMS wave",
            },
        )
    ).json()
    evidence_ids = []
    for i in range(2):
        response = await client.post(
            f"/cases/{case['id']}/evidence/note",
            headers=auth(author),
            json={
                "title": f"SMS {i}",
                "body": f"Text message body {i}: pay $2.99 at parcel-fee.example",
            },
        )
        evidence_ids.append(response.json()["id"])
    return Team(org, author, reviewer, reviewer2, case["id"], evidence_ids)


async def _finding(client: AsyncClient, team: Team, claim: str, submit: bool = True) -> dict:  # type: ignore[type-arg]
    response = await client.post(
        f"/cases/{team.case_id}/findings",
        headers=auth(team.author),
        json={"claim": claim, "evidence_ids": team.evidence_ids[:1]},
    )
    assert response.status_code == 201, response.text
    finding = response.json()
    if submit:
        submitted = await client.post(
            f"/findings/{finding['id']}/submit", headers=auth(team.author)
        )
        assert submitted.status_code == 200, submitted.text
        finding = submitted.json()
    return finding  # type: ignore[no-any-return]


# ------------------------------------------------------------------ FR-6
async def test_finding_requires_evidence(client: AsyncClient, team: Team) -> None:
    response = await client.post(
        f"/cases/{team.case_id}/findings",
        headers=auth(team.author),
        json={"claim": "The SMS links to a phishing page.", "evidence_ids": []},
    )
    assert response.status_code == 422
    missing = await client.post(
        f"/cases/{team.case_id}/findings",
        headers=auth(team.author),
        json={"claim": "The SMS links to a phishing page."},
    )
    assert missing.status_code == 422


async def test_finding_rejects_foreign_or_excluded_evidence(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    other_case = (
        await client.post(
            "/cases", headers=auth(team.author), json={"title": "Other case", "category": "other"}
        )
    ).json()
    foreign = await client.post(
        f"/cases/{other_case['id']}/evidence/note",
        headers=auth(team.author),
        json={"title": "x", "body": "unrelated"},
    )
    response = await client.post(
        f"/cases/{team.case_id}/findings",
        headers=auth(team.author),
        json={"claim": "Claim citing another case.", "evidence_ids": [foreign.json()["id"]]},
    )
    assert response.status_code == 422

    finding = await _finding(client, team, "Draft citing evidence later excluded.", submit=False)
    await client.post(
        f"/evidence/{team.evidence_ids[0]}/exclude",
        headers=auth(team.author),
        json={"reason": "Wrong screenshot"},
    )
    submit = await client.post(f"/findings/{finding['id']}/submit", headers=auth(team.author))
    assert submit.status_code == 422
    assert submit.json()["detail"]["code"] == "excluded_evidence"


# ------------------------------------------------------------------ FR-7
async def test_author_cannot_verify_own_finding(client: AsyncClient, session: AsyncSession) -> None:
    # A reviewer who authored a finding is still blocked (backend-enforced 403).
    org = await make_org(session)
    reviewer = await make_user(session, org, Role.REVIEWER)
    case = (
        await client.post(
            "/cases", headers=auth(reviewer), json={"title": "Self review", "category": "other"}
        )
    ).json()
    ev = await client.post(
        f"/cases/{case['id']}/evidence/note",
        headers=auth(reviewer),
        json={"title": "n", "body": "b"},
    )
    finding = (
        await client.post(
            f"/cases/{case['id']}/findings",
            headers=auth(reviewer),
            json={"claim": "My own claim to approve.", "evidence_ids": [ev.json()["id"]]},
        )
    ).json()
    await client.post(f"/findings/{finding['id']}/submit", headers=auth(reviewer))

    response = await client.post(f"/findings/{finding['id']}/verify", headers=auth(reviewer))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "self_review"


async def test_investigator_cannot_verify(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    finding = await _finding(client, team, "The site requests card details.")
    other = await make_user(session, team.org, Role.INVESTIGATOR)

    response = await client.post(f"/findings/{finding['id']}/verify", headers=auth(other))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "reviewer_required"


async def test_verify_and_reject_flow(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    good = await _finding(client, team, "The SMS directs users to parcel-fee.example.")
    bad = await _finding(client, team, "The sender is a known criminal group.")

    queue = (await client.get("/findings/review-queue", headers=auth(team.reviewer))).json()
    assert {f["id"] for f in queue} == {good["id"], bad["id"]}
    assert queue[0]["author_name"] == "Ivy Investigator"

    verified = await client.post(
        f"/findings/{good['id']}/verify", headers=auth(team.reviewer), json={"note": "Matches E1"}
    )
    assert verified.json()["status"] == "verified"
    assert verified.json()["reviewer_id"] == str(team.reviewer.id)

    no_reason = await client.post(
        f"/findings/{bad['id']}/reject", headers=auth(team.reviewer), json={}
    )
    assert no_reason.status_code == 422
    rejected = await client.post(
        f"/findings/{bad['id']}/reject",
        headers=auth(team.reviewer),
        json={"reason": "Not supported by the evidence."},
    )
    assert rejected.json()["status"] == "rejected"

    # Verified findings are frozen, in the API and in the database.
    edit = await client.patch(
        f"/findings/{good['id']}",
        headers=auth(team.author),
        json={"claim": "Changed after approval!"},
    )
    assert edit.status_code == 409
    async with get_engine().connect() as conn:
        with pytest.raises(DBAPIError, match="verified findings are immutable"):
            await conn.execute(text("UPDATE findings SET claim = 'x' WHERE status = 'verified'"))

    # A rejected finding can be revised by its author (back to draft).
    revised = await client.patch(
        f"/findings/{bad['id']}",
        headers=auth(team.author),
        json={"claim": "The SMS sender number appears in 3 victim reports."},
    )
    assert revised.json()["status"] == "draft"

    actions = (await session.scalars(select(AuditLog.action))).all()
    for action in [
        "finding.create",
        "finding.submit",
        "finding.verify",
        "finding.reject",
        "finding.update",
    ]:
        assert action in actions


async def test_cannot_verify_twice_or_draft(client: AsyncClient, team: Team) -> None:
    draft = await _finding(client, team, "Still being written up.", submit=False)
    assert (
        await client.post(f"/findings/{draft['id']}/verify", headers=auth(team.reviewer))
    ).status_code == 409


# ------------------------------------------------------------------ FR-8
async def test_report_contains_only_verified_findings(
    client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    verified = await _finding(client, team, "VERIFIED-CLAIM the link goes to parcel-fee.example")
    rejected = await _finding(client, team, "REJECTED-CLAIM the sender is a gang")
    await _finding(client, team, "INREVIEW-CLAIM payments go to an offshore bank")
    await _finding(client, team, "DRAFT-CLAIM there are 500 victims", submit=False)
    await client.post(f"/findings/{verified['id']}/verify", headers=auth(team.reviewer))
    await client.post(
        f"/findings/{rejected['id']}/reject",
        headers=auth(team.reviewer),
        json={"reason": "Unsupported"},
    )
    session.add(
        Note(
            case_id=team.case_id,
            body="AIDRAFT-TEXT the scammer is John Doe",
            is_ai_draft=True,
            ai_model="fake",
            author_id=team.author.id,
        )
    )
    await session.commit()

    preview = await client.get(f"/cases/{team.case_id}/report/preview", headers=auth(team.author))

    assert preview.status_code == 200
    body = preview.json()
    html = body["html"]
    assert body["verified_findings"] == 1
    assert "VERIFIED-CLAIM" in html
    for forbidden in [
        "REJECTED-CLAIM",
        "INREVIEW-CLAIM",
        "DRAFT-CLAIM",
        "AIDRAFT-TEXT",
        AI_DRAFT_LABEL,
    ]:
        assert forbidden not in html
    assert "Prepared under the BLACK MAMBA Code" in html
    assert "Chain of custody" in html
    # Evidence hashes and capture times are listed.
    evidence = (
        await client.get(f"/evidence/{team.evidence_ids[0]}", headers=auth(team.author))
    ).json()
    assert evidence["sha256"] in html
    assert body["chain_ok"] is True


async def test_report_escapes_html(client: AsyncClient, team: Team) -> None:
    finding = await _finding(client, team, "<script>alert('x')</script> claim text here")
    await client.post(f"/findings/{finding['id']}/verify", headers=auth(team.reviewer))

    html = (
        await client.get(f"/cases/{team.case_id}/report/preview", headers=auth(team.author))
    ).json()["html"]

    assert "<script>alert" not in html
    assert "&lt;script&gt;" in html


async def test_only_reviewers_generate_reports(client: AsyncClient, team: Team) -> None:
    response = await client.post(f"/cases/{team.case_id}/reports", headers=auth(team.author))
    assert response.status_code == 403


@pytest.mark.skipif(not report.pdf_engine_available(), reason="WeasyPrint system libraries missing")
async def test_report_pdf_is_hashed_and_stored(client: AsyncClient, team: Team) -> None:
    finding = await _finding(client, team, "The SMS directs users to parcel-fee.example.")
    await client.post(f"/findings/{finding['id']}/verify", headers=auth(team.reviewer))

    created = await client.post(f"/cases/{team.case_id}/reports", headers=auth(team.reviewer))

    assert created.status_code == 201, created.text
    report_ev = created.json()
    assert report_ev["type"] == "report"
    assert report_ev["mime"] == "application/pdf"
    verify = await client.get(f"/evidence/{report_ev['id']}/verify", headers=auth(team.reviewer))
    assert verify.json()["match"] is True
    pdf = await client.get(f"/evidence/{report_ev['id']}/content", headers=auth(team.reviewer))
    assert pdf.content.startswith(b"%PDF")


# ------------------------------------------------------------------ FR-10
async def test_archivist_output_is_labelled_draft_and_excluded_from_reports(
    app: FastAPI, client: AsyncClient, team: Team, session: AsyncSession
) -> None:
    fake = FakeLLM(reply="ARCHIVIST-OUTPUT the operator is clearly guilty")
    app.dependency_overrides[get_llm] = lambda: fake
    await client.post(
        f"/cases/{team.case_id}/notes",
        headers=auth(team.author),
        json={"body": "Victim got SMS on Nov 1"},
    )

    response = await client.post(f"/cases/{team.case_id}/archivist", headers=auth(team.author))

    assert response.status_code == 201, response.text
    note = response.json()
    assert note["is_ai_draft"] is True
    assert note["label"] == AI_DRAFT_LABEL
    assert note["body"].startswith(AI_DRAFT_LABEL.upper())
    assert note["ai_model"] == "fake"
    # The agent saw metadata and human notes, under the anti-injection system prompt.
    assert len(fake.calls) == 2
    system, prompt = fake.calls[0]
    assert system == SYSTEM_PROMPT
    assert "Victim got SMS on Nov 1" in prompt
    assert "E1" in prompt
    # AI output never reaches a report.
    html = (
        await client.get(f"/cases/{team.case_id}/report/preview", headers=auth(team.author))
    ).json()["html"]
    assert "ARCHIVIST-OUTPUT" not in html
    # And it created no findings.
    assert (
        await client.get(f"/cases/{team.case_id}/findings", headers=auth(team.author))
    ).json() == []
    stored = (await session.scalars(select(Note).where(Note.is_ai_draft.is_(True)))).all()
    assert len(stored) == 1


async def test_ai_drafts_are_not_fed_back_to_the_agent(
    app: FastAPI, client: AsyncClient, team: Team
) -> None:
    fake = FakeLLM(reply="DRAFT-ONE")
    app.dependency_overrides[get_llm] = lambda: fake
    await client.post(f"/cases/{team.case_id}/archivist", headers=auth(team.author))
    fake.calls.clear()

    await client.post(f"/cases/{team.case_id}/archivist", headers=auth(team.author))

    assert all("DRAFT-ONE" not in prompt for _, prompt in fake.calls)


async def test_archivist_module_has_no_side_effect_capabilities() -> None:
    import ast
    from pathlib import Path

    import blackmamba.agents.archivist as archivist_module

    tree = ast.parse(Path(archivist_module.__file__).read_text(encoding="utf-8"))
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imported.add(node.module)
    # The agent only gets an LLM client and plain data: no DB, HTTP, storage or browser.
    for module in imported:
        assert not module.startswith(
            (
                "blackmamba.services",
                "blackmamba.core.db",
                "httpx",
                "sqlalchemy",
                "playwright",
                "minio",
            )
        ), module
