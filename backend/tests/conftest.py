import hashlib
import hmac
import json
import os
import time
from urllib.parse import urlencode

os.environ["SHIRIN_ENVIRONMENT"] = "test"
os.environ["SHIRIN_DATABASE_URL"] = os.environ.get("TEST_DATABASE_URL", f"sqlite+aiosqlite:////private/tmp/shirin-tests-{os.getpid()}.db")
os.environ["SHIRIN_AUTH_ACCESS_SECRET"] = "test-shirin-access-secret-unique-123456789"
os.environ["SHIRIN_USER_BOT_TOKEN"] = "123456:synthetic-telegram-test-secret"
os.environ["SHIRIN_AUTH_COOKIE_SECURE"] = "false"
os.environ["SHIRIN_SUPERADMIN_ALLOWED_IDS"] = "101"
os.environ["SHIRIN_MARKET_INTEGRATION_SECRET"] = "test-integration-secret-unique-123456789"
os.environ["SHIRIN_UPLOADS_DIR"] = f"/private/tmp/shirin-test-media-{os.getpid()}"
os.environ["SHIRIN_BOT_MODE"] = "webhook"
os.environ["SHIRIN_WEBHOOK_SECRET"] = "synthetic-webhook-secret"

import httpx
import pytest_asyncio
from app.config import get_settings
from app.database import Base, async_session, engine
from app.main import app
from app.models import Staff
from app.services.session_auth import ensure_customer


def init_data(uid=101, age=0, extra=None):
    values = {
        "auth_date": str(int(time.time()) - age),
        "user": json.dumps({"id": uid, "first_name": f"Test {uid}"}, ensure_ascii=False),
        **(extra or {}),
    }
    secret = hmac.new(b"WebAppData", get_settings().user_bot_token.encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(secret, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


@pytest_asyncio.fixture(autouse=True)
async def database():
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.drop_all)
        await connection.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        for uid in (101, 202, 303, 404, 505):
            await ensure_customer(db, uid, f"test_{uid}")
        db.add_all([Staff(user_id=303, permission="CAN_LOOK_ORDERS"), Staff(user_id=404, permission="CAN_EDIT_MENU")])
        await db.commit()
    yield
    await engine.dispose()


@pytest_asyncio.fixture
async def client():
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://localhost:8083") as client:
        yield client


@pytest_asyncio.fixture
async def headers(client):
    result = {}
    for uid in (101, 202, 303, 404, 505):
        response = await client.post("/shirin/api/auth/telegram", json={"init_data": init_data(uid)})
        assert response.status_code == 200, response.text
        result[uid] = {"Authorization": "Bearer " + response.json()["accessToken"]}
    return result


PRODUCT = {
    "sku": "00001",
    "brand": "Ширин",
    "category": "Соки",
    "name_ru": "Сок яблочный",
    "name_uz": "Olma sharbati",
    "description_ru": "Натуральный",
    "description_uz": "Tabiiy",
    "volume_ml": 1000,
    "sell_by_unit": True,
    "sell_by_package": True,
    "units_per_package": 12,
    "unit_price_uzs": "12000.25",
    "package_price_uzs": "135000.10",
}
CUSTOMER = {"name": "Тестовый магазин", "phone": "+998901234567", "address": "Ташкент, тестовая улица 1"}


async def add_product(client, headers, **overrides):
    response = await client.post("/shirin/api/products", json={**PRODUCT, **overrides}, headers=headers[101])
    assert response.status_code == 201, response.text
    return response.json()


async def place_order(client, headers, product, uid=202, **overrides):
    data = {
        "lines": [
            {"product_id": product["id"], "sale_format": "package", "quantity": 2},
            {"product_id": product["id"], "sale_format": "unit", "quantity": 3},
        ],
        "customer": CUSTOMER,
        **overrides,
    }
    response = await client.post("/shirin/api/orders/quote", json=data, headers=headers[uid])
    assert response.status_code == 200, response.text
    import uuid

    payload = {**data, "quote_token": response.json()["quote_token"], "attempt_key": str(uuid.uuid4())}
    response = await client.post("/shirin/api/orders", json=payload, headers=headers[uid])
    assert response.status_code == 201, response.text
    return response.json(), payload
