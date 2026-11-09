"""Organisation sign-up (public application) and platform-admin vetting."""

import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Request, status
from sqlalchemy import select

from blackmamba.api.deps import (
    PlatformAdminUser,
    SessionDep,
    client_ip,
    conflict,
    http_error,
    not_found,
)
from blackmamba.core.config import get_settings
from blackmamba.models import Organization, OrgStatus, Role, User
from blackmamba.schemas.admin import (
    ChainVerificationOut,
    OrgApplication,
    OrgApproved,
    OrgDecision,
    OrgOut,
)
from blackmamba.schemas.common import Message
from blackmamba.services import accounts, audit
from blackmamba.services.accounts import AccountError
from blackmamba.services.email import send_email
from blackmamba.services.rate_limit import get_rate_limiter

public_router = APIRouter(prefix="/orgs", tags=["organisations"])
router = APIRouter(prefix="/platform", tags=["platform"])


@public_router.post("/apply", response_model=Message, status_code=202)
async def apply(body: OrgApplication, request: Request, session: SessionDep) -> Message:
    """Request access for a new organisation. A platform admin vets every application."""
    settings = get_settings()
    if not await get_rate_limiter().hit(
        f"apply:{client_ip(request)}", 3, settings.login_rate_window_seconds * 12
    ):
        raise http_error(status.HTTP_429_TOO_MANY_REQUESTS, "rate_limited", "try again later")
    org = Organization(
        name=body.org_name.strip(),
        slug=accounts.slugify(body.org_name),
        status=OrgStatus.PENDING,
        contact_name=body.contact_name.strip(),
        contact_email=accounts.normalise_email(body.contact_email),
        purpose=body.purpose.strip(),
    )
    session.add(org)
    await session.flush()
    await audit.record(
        session, org_id=None, actor_id=None, action="org.apply", target_type="org", target_id=org.id
    )
    await session.commit()
    return Message(message="Thank you. We review every application and will contact you.")


async def _org(session: SessionDep, org_id: uuid.UUID) -> Organization:
    org = await session.get(Organization, org_id)
    if org is None:
        raise not_found("organisation")
    return org


async def _decide(
    session: SessionDep, org: Organization, actor: User, new_status: OrgStatus, reason: str | None
) -> None:
    previous = org.status
    org.status = new_status
    org.reviewed_at = datetime.now(UTC)
    await audit.record(
        session,
        org_id=None,
        actor_id=actor.id,
        action=f"org.{new_status.value}",
        target_type="org",
        target_id=org.id,
        payload={"from": previous.value, "reason": reason},
    )


@router.get("/orgs", response_model=list[OrgOut])
async def list_orgs(
    _admin: PlatformAdminUser, session: SessionDep, status: OrgStatus | None = None
) -> list[Organization]:
    query = select(Organization).order_by(Organization.created_at.desc())
    if status is not None:
        query = query.where(Organization.status == status)
    return list(await session.scalars(query))


@router.post("/orgs/{org_id}/approve", response_model=OrgApproved)
async def approve_org(
    org_id: uuid.UUID, admin: PlatformAdminUser, session: SessionDep
) -> OrgApproved:
    org = await _org(session, org_id)
    if org.status != OrgStatus.PENDING:
        raise conflict("invalid_transition", f"organisation is {org.status.value}")
    await _decide(session, org, admin, OrgStatus.ACTIVE, None)
    try:
        token, raw = await accounts.create_invite(
            session, org_id=org.id, email=org.contact_email, role=Role.ADMIN, created_by=admin.id
        )
    except AccountError as exc:
        raise conflict(exc.code, exc.message) from exc
    await session.commit()
    url = accounts.invite_url(raw)
    emailed = await send_email(
        token.email,
        "Your BLACK MAMBA organisation is approved",
        f"{org.name} has been approved. Create your administrator account here:\n\n{url}",
    )
    return OrgApproved(org=OrgOut.model_validate(org), admin_invite_url=url, emailed=emailed)


@router.post("/orgs/{org_id}/reject", response_model=OrgOut)
async def reject_org(
    org_id: uuid.UUID, body: OrgDecision, admin: PlatformAdminUser, session: SessionDep
) -> Organization:
    org = await _org(session, org_id)
    if org.status != OrgStatus.PENDING:
        raise conflict("invalid_transition", f"organisation is {org.status.value}")
    await _decide(session, org, admin, OrgStatus.REJECTED, body.reason)
    await session.commit()
    return org


@router.post("/orgs/{org_id}/suspend", response_model=OrgOut)
async def suspend_org(
    org_id: uuid.UUID, body: OrgDecision, admin: PlatformAdminUser, session: SessionDep
) -> Organization:
    org = await _org(session, org_id)
    if org.status != OrgStatus.ACTIVE:
        raise conflict("invalid_transition", f"organisation is {org.status.value}")
    await _decide(session, org, admin, OrgStatus.SUSPENDED, body.reason)
    await session.commit()
    return org


@router.post("/orgs/{org_id}/reactivate", response_model=OrgOut)
async def reactivate_org(
    org_id: uuid.UUID, admin: PlatformAdminUser, session: SessionDep
) -> Organization:
    org = await _org(session, org_id)
    if org.status != OrgStatus.SUSPENDED:
        raise conflict("invalid_transition", f"organisation is {org.status.value}")
    await _decide(session, org, admin, OrgStatus.ACTIVE, None)
    await session.commit()
    return org


@router.get("/audit/verify", response_model=ChainVerificationOut)
async def verify_platform_chain(
    _admin: PlatformAdminUser, session: SessionDep, org_id: uuid.UUID | None = None
) -> ChainVerificationOut:
    """Verify the platform chain, or any organisation's chain (hashes only, no content)."""
    result = await audit.verify_chain(session, org_id)
    return ChainVerificationOut(
        ok=result.ok,
        entries_checked=result.entries_checked,
        first_bad_id=result.first_bad_id,
        reason=result.reason,
    )
