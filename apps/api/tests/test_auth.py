"""FR-1: authentication, RBAC, 2FA, rate limiting, invitations, password reset."""

import pyotp
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from blackmamba.core.security import decrypt_field
from blackmamba.models import AuditLog, OrgStatus, Role, User
from tests.factories import PASSWORD, auth, make_org, make_user


async def _login(client: AsyncClient, email: str, password: str = PASSWORD, **extra: str):  # type: ignore[no-untyped-def]
    return await client.post("/auth/login", json={"email": email, "password": password, **extra})


async def test_login_success_returns_tokens_and_audits(
    client: AsyncClient, session: AsyncSession
) -> None:
    org = await make_org(session)
    user = await make_user(session, org, Role.INVESTIGATOR, "Inv@Example.org")

    response = await _login(client, "inv@example.org")

    assert response.status_code == 200, response.text
    tokens = response.json()
    me = await client.get("/auth/me", headers={"Authorization": f"Bearer {tokens['access_token']}"})
    assert me.status_code == 200
    assert me.json()["id"] == str(user.id)
    assert me.json()["org_name"] == "Test Org"
    actions = (await session.scalars(select(AuditLog.action))).all()
    assert "auth.login" in actions


async def test_login_wrong_password_is_401(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    user = await make_user(session, org, Role.INVESTIGATOR)

    response = await _login(client, user.email, "wrong password!!")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "invalid_credentials"


async def test_login_unknown_user_is_401(client: AsyncClient, db: None) -> None:
    response = await _login(client, "nobody@example.org")
    assert response.status_code == 401


async def test_protected_route_without_token_is_401(client: AsyncClient, db: None) -> None:
    assert (await client.get("/auth/me")).status_code == 401
    assert (await client.get("/admin/users")).status_code == 401
    bad = await client.get("/auth/me", headers={"Authorization": "Bearer not-a-jwt"})
    assert bad.status_code == 401


async def test_wrong_role_is_403(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    investigator = await make_user(session, org, Role.INVESTIGATOR)

    response = await client.get("/admin/users", headers=auth(investigator))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "insufficient_role"


async def test_admin_without_2fa_is_403(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    admin = await make_user(session, org, Role.ADMIN)
    admin.totp_enabled = False
    await session.commit()

    response = await client.get("/admin/users", headers=auth(admin))

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "admin_requires_2fa"


async def test_refresh_token_flow(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    user = await make_user(session, org, Role.REVIEWER)
    tokens = (await _login(client, user.email)).json()

    refreshed = await client.post("/auth/refresh", json={"refresh_token": tokens["refresh_token"]})
    assert refreshed.status_code == 200
    # An access token is not a refresh token.
    wrong = await client.post("/auth/refresh", json={"refresh_token": tokens["access_token"]})
    assert wrong.status_code == 401


async def test_totp_setup_enable_and_login(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    user = await make_user(session, org, Role.INVESTIGATOR)
    headers = auth(user)

    setup = await client.post("/auth/2fa/setup", headers=headers)
    assert setup.status_code == 200
    secret = setup.json()["secret"]
    assert (
        await client.post("/auth/2fa/enable", headers=headers, json={"code": "000000"})
    ).status_code == 422
    enabled = await client.post(
        "/auth/2fa/enable", headers=headers, json={"code": pyotp.TOTP(secret).now()}
    )
    assert enabled.status_code == 200
    assert enabled.json()["totp_enabled"] is True
    await session.refresh(user)
    assert user.totp_secret is not None
    assert decrypt_field(user.totp_secret) == secret  # stored encrypted
    assert user.totp_secret != secret

    no_code = await _login(client, user.email)
    assert no_code.status_code == 401
    assert no_code.json()["detail"]["code"] == "totp_required"
    bad_code = await _login(client, user.email, totp_code="123456")
    assert bad_code.status_code == 401
    good = await _login(client, user.email, totp_code=pyotp.TOTP(secret).now())
    assert good.status_code == 200


async def test_login_is_rate_limited(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    user = await make_user(session, org, Role.INVESTIGATOR)

    codes = [(await _login(client, user.email, "wrong password!!")).status_code for _ in range(6)]

    assert codes[:5] == [401] * 5
    assert codes[5] == 429


async def test_password_change_revokes_old_tokens(
    client: AsyncClient, session: AsyncSession
) -> None:
    org = await make_org(session)
    user = await make_user(session, org, Role.INVESTIGATOR)
    old = auth(user)

    response = await client.post(
        "/auth/change-password",
        headers=old,
        json={"current_password": PASSWORD, "new_password": "a brand new long password"},
    )

    assert response.status_code == 200
    assert (await client.get("/auth/me", headers=old)).status_code == 401
    assert (await _login(client, user.email, "a brand new long password")).status_code == 200


async def test_suspended_org_cannot_log_in(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session, status=OrgStatus.SUSPENDED)
    user = await make_user(session, org, Role.INVESTIGATOR)

    assert (await _login(client, user.email)).status_code == 403
    assert (await client.get("/auth/me", headers=auth(user))).status_code == 403


async def test_invite_flow(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    admin = await make_user(session, org, Role.ADMIN)

    created = await client.post(
        "/admin/invitations",
        headers=auth(admin),
        json={"email": "new.person@example.org", "role": "reviewer"},
    )
    assert created.status_code == 201, created.text
    token = created.json()["invite_url"].split("token=")[1]

    inspect = await client.post("/auth/invite/inspect", json={"token": token})
    assert inspect.json() == {
        "email": "new.person@example.org",
        "role": "reviewer",
        "org_name": "Test Org",
    }
    accepted = await client.post(
        "/auth/invite/accept",
        json={"token": token, "name": "New Person", "password": "long enough password"},
    )
    assert accepted.status_code == 201
    assert accepted.json()["org_id"] == str(org.id)
    reused = await client.post(
        "/auth/invite/accept",
        json={"token": token, "name": "Again", "password": "long enough password"},
    )
    assert reused.status_code == 422


async def test_password_reset_flow(client: AsyncClient, session: AsyncSession) -> None:
    org = await make_org(session)
    admin = await make_user(session, org, Role.ADMIN)
    user = await make_user(session, org, Role.INVESTIGATOR)

    # Self-service request never reveals whether the account exists.
    unknown = await client.post("/auth/password-reset/request", json={"email": "ghost@example.org"})
    known = await client.post("/auth/password-reset/request", json={"email": user.email})
    assert unknown.status_code == known.status_code == 202
    assert unknown.json() == known.json()

    link = await client.post(f"/admin/users/{user.id}/password-reset", headers=auth(admin))
    token = link.json()["url"].split("token=")[1]
    confirmed = await client.post(
        "/auth/password-reset/confirm", json={"token": token, "password": "reset password 123"}
    )
    assert confirmed.status_code == 200
    assert (await _login(client, user.email, "reset password 123")).status_code == 200


async def test_admin_cannot_see_other_org_users(client: AsyncClient, session: AsyncSession) -> None:
    org_a = await make_org(session, "Org A")
    org_b = await make_org(session, "Org B")
    admin_a = await make_user(session, org_a, Role.ADMIN)
    user_b = await make_user(session, org_b, Role.INVESTIGATOR)

    listed = await client.get("/admin/users", headers=auth(admin_a))
    assert str(user_b.id) not in {u["id"] for u in listed.json()}
    patch = await client.patch(
        f"/admin/users/{user_b.id}", headers=auth(admin_a), json={"is_active": False}
    )
    assert patch.status_code == 404


async def test_admin_deactivation_revokes_access(
    client: AsyncClient, session: AsyncSession
) -> None:
    org = await make_org(session)
    admin = await make_user(session, org, Role.ADMIN)
    user = await make_user(session, org, Role.INVESTIGATOR)
    headers = auth(user)

    response = await client.patch(
        f"/admin/users/{user.id}", headers=auth(admin), json={"is_active": False}
    )
    assert response.status_code == 200
    assert (await client.get("/auth/me", headers=headers)).status_code == 401
    self_lock = await client.patch(
        f"/admin/users/{admin.id}", headers=auth(admin), json={"role": "investigator"}
    )
    assert self_lock.status_code == 403


async def test_org_application_and_approval(client: AsyncClient, session: AsyncSession) -> None:
    platform_admin = await make_user(session, None, Role.PLATFORM_ADMIN)
    applied = await client.post(
        "/orgs/apply",
        json={
            "org_name": "Coastal Scam Watch",
            "contact_name": "Sam",
            "contact_email": "sam@coastal.example.org",
            "purpose": "Volunteer team documenting marketplace scams for police referral.",
        },
    )
    assert applied.status_code == 202
    pending = await client.get(
        "/platform/orgs", params={"status": "pending"}, headers=auth(platform_admin)
    )
    org_id = pending.json()[0]["id"]

    approved = await client.post(f"/platform/orgs/{org_id}/approve", headers=auth(platform_admin))

    assert approved.status_code == 200
    assert approved.json()["org"]["status"] == "active"
    token = approved.json()["admin_invite_url"].split("token=")[1]
    inspect = await client.post("/auth/invite/inspect", json={"token": token})
    assert inspect.json()["role"] == "admin"
    # Org admins cannot use platform endpoints.
    org_admin = await make_user(session, None, Role.ADMIN)
    assert (await client.get("/platform/orgs", headers=auth(org_admin))).status_code == 403


async def test_user_email_is_unique_case_insensitively(session: AsyncSession) -> None:
    org = await make_org(session)
    await make_user(session, org, Role.INVESTIGATOR, "dup@example.org")
    found = await session.scalar(select(User).where(User.email == "dup@example.org"))
    assert found is not None
