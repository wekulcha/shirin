from app.config import get_settings
from conftest import add_product, place_order


async def test_superadmin_requires_own_login_and_allowlist(client, headers, monkeypatch):
    assert (await client.get("/shirin/api/superadmin/me")).status_code == 401
    actor = await client.get("/shirin/api/superadmin/me", headers=headers[101])
    assert actor.status_code == 200 and actor.json()["superadmin"] is True
    for uid in (202, 303, 404):
        for path in ("/shirin/api/superadmin/me", "/shirin/api/superadmin/overview", "/shirin/api/access"):
            assert (await client.get(path, headers=headers[uid])).status_code == 403
    assert (await client.put("/shirin/api/access", json={"user_id": 202, "permissions": ["CAN_EDIT_MENU", "CAN_LOOK_ORDERS"]}, headers=headers[101])).status_code == 200
    assert (await client.get("/shirin/api/superadmin/me", headers=headers[202])).status_code == 403
    monkeypatch.setattr(get_settings(), "superadmin_allowed_ids", [])
    assert (await client.get("/shirin/api/superadmin/me", headers=headers[101])).status_code == 403
    assert (await client.get("/shirin/api/access", headers=headers[101])).status_code == 403


async def test_overview_tracks_real_orders_and_payment(client, headers):
    empty = (await client.get("/shirin/api/superadmin/overview", headers=headers[101])).json()
    assert empty["allOrders"] == 0 and empty["unpaidTotal"] == "0.00"
    product = await add_product(client, headers)
    order, _ = await place_order(client, headers, product)
    data = (await client.get("/shirin/api/superadmin/overview", headers=headers[101])).json()
    assert data["activeProducts"] == 1 and data["allOrders"] == 1
    assert data["unpaidOrders"] == 1 and data["unpaidTotal"] == "306000.95"
    assert data["pendingNotifications"] == 1
    assert (await client.patch(f"/shirin/api/orders/{order['id']}", json={"payment_status": "PAID"}, headers=headers[101])).status_code == 200
    data = (await client.get("/shirin/api/superadmin/overview", headers=headers[101])).json()
    assert data["allOrders"] == 1 and data["unpaidOrders"] == 0 and data["unpaidTotal"] == "0.00"
    settings = (await client.get("/shirin/api/settings", headers=headers[101])).json()
    assert settings["superadmin_app_url"].endswith("/shirin/superadmin/")
    assert "integration_configured" not in settings
