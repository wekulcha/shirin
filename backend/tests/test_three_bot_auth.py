import itertools

import pytest
from app.config import get_settings
from app.database import async_session
from app.models import Staff
from conftest import init_data
from sqlalchemy import delete

ROLES = ("user", "admin", "superadmin")
COOKIES = {
    "user": "shirin_refresh_token",
    "admin": "shirin_admin_refresh_token",
    "superadmin": "shirin_superadmin_refresh_token",
}
ORIGIN = {"Origin": "http://localhost:5183"}


async def login(client, role, uid=101):
    return await client.post(f"/shirin/api/auth/telegram/{role}", json={"init_data": init_data(uid, role=role)})


@pytest.mark.parametrize("role", ROLES)
async def test_each_bot_authenticates_its_own_signed_init_data(client, role):
    response = await login(client, role)
    assert response.status_code == 200, response.text
    assert response.json()["user"]["id"] == 101
    assert response.json()["botRole"] == role
    assert response.json()["accessToken"]
    assert COOKIES[role] in client.cookies
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "Path=/shirin/api/auth" in response.headers["set-cookie"]


@pytest.mark.parametrize("requested_role,signed_role", list(itertools.permutations(ROLES, 2)))
async def test_init_data_from_another_bot_is_rejected_even_for_superadmin(client, requested_role, signed_role):
    response = await client.post(
        f"/shirin/api/auth/telegram/{requested_role}", json={"init_data": init_data(101, role=signed_role)}
    )
    assert response.status_code == 401
    assert response.json()["detail"] == "invalid_telegram_data"
    assert "set-cookie" not in response.headers


@pytest.mark.parametrize("role", ROLES)
async def test_missing_role_token_fails_without_falling_back_to_other_bots(client, monkeypatch, role):
    signed = init_data(101, role=role)
    monkeypatch.setattr(get_settings(), f"{role}_bot_token", "")
    response = await client.post(f"/shirin/api/auth/telegram/{role}", json={"init_data": signed})
    assert response.status_code == 503
    assert response.json()["detail"] == "bot_not_configured"
    assert "set-cookie" not in response.headers


async def test_admin_login_requires_employee_permission_or_superadmin_allowlist(client, headers):
    for uid in (101, 303, 404):
        assert (await login(client, "admin", uid)).status_code == 200
    for uid in (202, 505):
        denied = await login(client, "admin", uid)
        assert denied.status_code == 403
        assert "set-cookie" not in denied.headers
    grant = await client.put(
        "/shirin/api/access", json={"user_id": 505, "permissions": ["CAN_LOOK_ORDERS"]}, headers=headers[101]
    )
    assert grant.status_code == 200
    assert (await login(client, "admin", 505)).status_code == 200


async def test_staff_permissions_do_not_grant_superadmin_login(client, headers, monkeypatch):
    assert (await login(client, "superadmin", 101)).status_code == 200
    grant = await client.put(
        "/shirin/api/access", json={"user_id": 202, "permissions": ["CAN_LOOK_ORDERS", "CAN_EDIT_MENU"]}, headers=headers[101]
    )
    assert grant.status_code == 200
    for uid in (202, 303, 404):
        denied = await login(client, "superadmin", uid)
        assert denied.status_code == 403
        assert "set-cookie" not in denied.headers
    monkeypatch.setattr(get_settings(), "superadmin_allowed_ids", [])
    assert (await login(client, "superadmin", 101)).status_code == 403


async def test_refresh_cookies_keep_three_logins_independent_and_rotate_once(client):
    users = {"user": 202, "admin": 303, "superadmin": 101}
    for role, uid in users.items():
        assert (await login(client, role, uid)).status_code == 200
    tokens = {role: client.cookies.get(name) for role, name in COOKIES.items()}
    assert len(set(tokens.values())) == 3

    for role, uid in users.items():
        before = {other: client.cookies.get(name) for other, name in COOKIES.items()}
        response = await client.post(f"/shirin/api/auth/refresh/{role}", headers=ORIGIN)
        assert response.status_code == 200, response.text
        assert response.json()["user"]["id"] == uid
        assert response.json()["botRole"] == role
        assert client.cookies.get(COOKIES[role]) != before[role]
        for other in ROLES:
            if other != role:
                assert client.cookies.get(COOKIES[other]) == before[other]
        replay = await client.post(
            f"/shirin/api/auth/refresh/{role}", headers={**ORIGIN, "Cookie": f"{COOKIES[role]}={before[role]}"}
        )
        assert replay.status_code == 401

    # A valid token copied under another bot's cookie name must remain unusable.
    for source, target in itertools.permutations(ROLES, 2):
        source_token = client.cookies.get(COOKIES[source])
        cross_role = await client.post(
            f"/shirin/api/auth/refresh/{target}", headers={**ORIGIN, "Cookie": f"{COOKIES[target]}={source_token}"}
        )
        assert cross_role.status_code == 401
    for role, uid in users.items():
        valid = await client.post(f"/shirin/api/auth/refresh/{role}", headers=ORIGIN)
        assert valid.status_code == 200
        assert valid.json()["user"]["id"] == uid


async def test_logout_revokes_only_the_selected_bot_session(client):
    for role in ROLES:
        assert (await login(client, role)).status_code == 200
    admin_token = client.cookies.get(COOKIES["admin"])
    assert (await client.post("/shirin/api/auth/logout/admin", headers=ORIGIN)).status_code == 204
    assert client.cookies.get(COOKIES["admin"]) is None
    replay = await client.post(
        "/shirin/api/auth/refresh/admin", headers={**ORIGIN, "Cookie": f"{COOKIES['admin']}={admin_token}"}
    )
    assert replay.status_code == 401
    for role in ("user", "superadmin"):
        assert (await client.post(f"/shirin/api/auth/refresh/{role}", headers=ORIGIN)).status_code == 200


async def test_refresh_rechecks_revoked_staff_permission_and_superadmin_allowlist(client, monkeypatch):
    admin = await login(client, "admin", 303)
    assert admin.status_code == 200
    assert (await login(client, "superadmin", 101)).status_code == 200
    async with async_session() as db:
        await db.execute(delete(Staff).where(Staff.user_id == 303))
        await db.commit()
    denied = await client.post("/shirin/api/auth/refresh/admin", headers=ORIGIN)
    assert denied.status_code == 403
    assert "set-cookie" not in denied.headers
    bearer = {"Authorization": "Bearer " + admin.json()["accessToken"]}
    assert (await client.get("/shirin/api/settings", headers=bearer)).status_code == 403
    monkeypatch.setattr(get_settings(), "superadmin_allowed_ids", [])
    denied = await client.post("/shirin/api/auth/refresh/superadmin", headers=ORIGIN)
    assert denied.status_code == 403
    assert "set-cookie" not in denied.headers


async def test_public_bot_links_expose_usernames_without_credentials(client, monkeypatch):
    settings = get_settings()
    monkeypatch.setattr(settings, "user_bot_username", "")
    monkeypatch.setattr(settings, "bot_username", "legacy_shirin_user_bot")
    monkeypatch.setattr(settings, "admin_bot_username", "shirin_admin_bot")
    monkeypatch.setattr(settings, "superadmin_bot_username", "shirin_ops_bot")
    response = await client.get("/shirin/api/auth/bots")
    assert response.status_code == 200
    data = response.json()
    assert data["user"]["url"] == "https://t.me/legacy_shirin_user_bot"
    assert data["admin"]["url"] == "https://t.me/shirin_admin_bot"
    assert data["superadmin"]["url"] == "https://t.me/shirin_ops_bot"
    for role in ROLES:
        assert set(data[role]) == {"username", "url"}
        assert settings.bot_token_for(role) not in response.text
    assert settings.auth_access_secret not in response.text
