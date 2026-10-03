import base64
import copy
import hashlib
import hmac
import json
import secrets
import time
from datetime import timedelta

import pytest
from app.config import get_settings
from app.database import async_session
from app.models import ImportLog, ImportPreview, Outbox, Product
from app.models.business import now
from app.services.access import signed_value
from app.services.notifications import process_outbox_once
from app.services.session_auth import verify_access_token
from conftest import PRODUCT, add_product, init_data, place_order
from sqlalchemy import event, func, select
from sqlalchemy.orm import Session
from test_business import apply, preview, workbook_with


async def test_signed_multipart_upload(client, headers):
    request = client.build_request("POST", "/shirin/api/catalog/preview", files={"file": ("catalog.xlsx", workbook_with([PRODUCT]))})
    body = await request.aread()
    timestamp = str(int(time.time()))
    nonce = secrets.token_hex(20)
    signature = hmac.new(
        get_settings().market_integration_secret.encode(),
        signed_value("POST", request.url.path, "", body, "101", timestamp, nonce),
        hashlib.sha256,
    ).hexdigest()
    request.headers.update(
        {"X-Shirin-Actor": "101", "X-Shirin-Timestamp": timestamp, "X-Shirin-Nonce": nonce, "X-Shirin-Signature": signature}
    )
    result = await client.send(request)
    assert result.status_code == 200 and not result.json()["payload"]["errors"], result.text


async def test_import_database_failure_rolls_back_every_row(client, headers):
    product = await add_product(client, headers)
    checked = (
        await preview(client, headers, workbook_with([{"sku": product["sku"], "unit_price_uzs": "50"}, {**PRODUCT, "sku": "FAIL-NEW"}]))
    ).json()

    def fail_commit(session, context, instances):
        if any(isinstance(obj, Product) and obj.sku == "FAIL-NEW" for obj in session.new):
            raise RuntimeError("Synthetic storage failure")

    event.listen(Session, "before_flush", fail_commit)
    try:
        with pytest.raises(RuntimeError):
            await apply(client, headers, checked["id"])
    finally:
        event.remove(Session, "before_flush", fail_commit)
    async with async_session() as db:
        assert (await db.get(Product, product["id"])).unit_price_uzs == product["unit_price_uzs"] or str(
            (await db.get(Product, product["id"])).unit_price_uzs
        ) == product["unit_price_uzs"]
        assert await db.scalar(select(func.count(Product.id))) == 1
        assert await db.scalar(select(func.count(ImportLog.id))) == 0
        assert (await db.get(ImportPreview, checked["id"])).state == "PENDING"


async def test_import_permissions_rechecked_expiry_and_cancel(client, headers):
    checked = (await preview(client, headers, workbook_with([PRODUCT]), uid=404)).json()
    assert (await client.put("/shirin/api/access", json={"user_id": 404, "permissions": []}, headers=headers[101])).status_code == 200
    assert (await apply(client, headers, checked["id"], uid=404)).status_code == 403
    checked = (await preview(client, headers, workbook_with([PRODUCT]))).json()
    async with async_session() as db:
        p = await db.get(ImportPreview, checked["id"])
        p.expires_at = now() - timedelta(seconds=1)
        await db.commit()
    assert (await apply(client, headers, checked["id"])).status_code == 409


async def test_refresh_one_use_cookie_path_and_cross_project_token(client):
    login = await client.post("/shirin/api/auth/telegram", json={"init_data": init_data(101)})
    assert "Path=/shirin/api/auth" in login.headers["set-cookie"]
    cookie = client.cookies.get("shirin_refresh_token")
    assert (await client.post("/shirin/api/auth/refresh")).status_code == 403
    good = await client.post("/shirin/api/auth/refresh", headers={"Origin": "http://localhost:5183"})
    assert good.status_code == 200
    old = await client.post(
        "/shirin/api/auth/refresh", headers={"Origin": "http://localhost:5183", "Cookie": "shirin_refresh_token=" + cookie}
    )
    assert old.status_code == 401
    token = login.json()["accessToken"]
    a, b, _ = token.split(".")
    payload = json.loads(base64.urlsafe_b64decode(b + "=" * (-len(b) % 4)))
    payload.pop("iss")
    b = base64.urlsafe_b64encode(json.dumps(payload).encode()).decode().rstrip("=")
    sig = (
        base64.urlsafe_b64encode(hmac.new(get_settings().auth_access_secret.encode(), f"{a}.{b}".encode(), hashlib.sha256).digest())
        .decode()
        .rstrip("=")
    )
    assert verify_access_token(f"{a}.{b}.{sig}") is None


async def test_outbox_partial_delivery_and_expired_lease(client, headers):
    product = await add_product(client, headers)
    await place_order(client, headers, product)
    async with async_session() as db:
        entry = await db.scalar(select(Outbox))
        payload = copy.deepcopy(entry.payload)
        payload["order"] = dict(payload["order"])
        payload["order"]["lines"] *= 100
        entry.payload = payload
        entry.state = "SENDING"
        entry.lease_until = now() - timedelta(minutes=1)
        await db.commit()

    class Partial:
        async def send(self, payload, part, index):
            if index == 1:
                raise TimeoutError()
            return 111

    assert await process_outbox_once(Partial())
    async with async_session() as db:
        entry = await db.scalar(select(Outbox))
        assert entry.message_ids == [111] and entry.state == "PENDING"
        entry.next_attempt_at = now()
        await db.commit()
    indices = []

    class Recovery:
        async def send(self, payload, part, index):
            indices.append(index)
            return 200 + index

    assert await process_outbox_once(Recovery())
    assert min(indices) == 1
    async with async_session() as db:
        assert (await db.scalar(select(Outbox))).state == "SENT"
