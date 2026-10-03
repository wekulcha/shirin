"""Run via shirin/.venv with PYTHONPATH=market worktree/backend.

Seeds only an explicitly named synthetic Market database, then verifies that
the existing superadmin bearer authorizes the signed cross-service proxy.
"""

import asyncio
import hashlib
import hmac
import json
import secrets
import time
from urllib.parse import urlencode

import httpx
from app.config import get_settings
from app.database import Base, async_session, engine
from app.services.session_auth import ensure_customer


async def main():
    settings = get_settings()
    if "shirin-market-smoke" not in settings.database_url or settings.superadmin_allowed_ids != [101]:
        raise SystemExit("Refusing to access a non-test Market database")
    import app.models  # noqa: F401

    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with async_session() as db:
        await ensure_customer(db, 101, "Synthetic superadmin")
        await ensure_customer(db, 202, "Synthetic regular user")
        await db.commit()
    base = "http://localhost:8085/api/v1"

    def init_data(uid):
        values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "username": "synthetic"}, separators=(",", ":"))}
        key = hmac.new(b"WebAppData", settings.superadmin_bot_token.encode(), hashlib.sha256).digest()
        values["hash"] = hmac.new(key, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
        return urlencode(values)

    async with httpx.AsyncClient() as client:
        login = await client.post(base + "/auth/telegram/superadmin", json={"initDataRaw": init_data(101)})
        assert login.status_code == 200, login.text
        auth = {"Authorization": "Bearer " + login.json()["accessToken"]}
        assert (await client.get(base + "/projects", headers=auth)).json()[0]["id"] == "shirin"
        assert (await client.get(base + "/projects/shirin/auth/me", headers=auth)).json()["superadmin"] is True
        assert (await client.get(base + "/projects/shirin/access", headers=auth)).status_code == 200
        assert (await client.get(base + "/projects/shirin/customers?admin=true", headers=auth)).status_code == 200
        assert (await client.get(base + "/projects/shirin/orders", headers=auth)).status_code == 200
        denied = await client.post(base + "/auth/telegram/superadmin", json={"initDataRaw": init_data(202)})
        assert denied.status_code == 403
        assert (await client.get(base + "/projects/shirin/products")).status_code == 401
        assert (await client.post(base + "/projects/shirin/orders/quote", headers=auth, json={})).status_code == 404
        assert (await client.get(base + "/projects/other/products", headers=auth)).status_code == 404
        sku = "SMOKE-" + secrets.token_hex(4)
        product = {
            "sku": sku,
            "brand": "Ширин",
            "category": "Synthetic",
            "name_ru": "Тест интеграции",
            "name_uz": "Integratsiya testi",
            "sell_by_unit": True,
            "unit_price_uzs": "12345",
        }
        added = await client.post(base + "/projects/shirin/products", headers=auth, json=product)
        assert added.status_code == 201, added.text
        pid = added.json()["id"]
        updated = await client.put(
            base + "/projects/shirin/products/" + str(pid),
            headers=auth,
            json={**product, "version": added.json()["version"], "unit_price_uzs": "23456"},
        )
        assert updated.status_code == 200 and updated.json()["unit_price_uzs"] == "23456.00"
        exported = await client.get(base + "/projects/shirin/catalog/export", headers=auth)
        assert exported.status_code == 200 and exported.content[:2] == b"PK"
        checked = await client.post(
            base + "/projects/shirin/catalog/preview", headers=auth, files={"file": ("catalog.xlsx", exported.content)}
        )
        assert checked.status_code == 200, checked.text
        assert not checked.json()["payload"]["errors"]
        applied = await client.post(base + "/projects/shirin/catalog/previews/" + checked.json()["id"] + "/apply", headers=auth)
        assert applied.status_code == 200, applied.text
        assert (await client.get("http://localhost:8085/health")).status_code == 200
        old_catalog = await client.get(base + "/restaurants")
        assert old_catalog.status_code == 200, old_catalog.text
        # Shirin products were created through its service, not Market's tables.
        from app.models.meal import Meal
        from sqlalchemy import func, select

        async with async_session() as db:
            assert await db.scalar(select(func.count(Meal.id))) == 0
    await engine.dispose()
    print("Market integration smoke passed: bearer/allowlist, products CRUD, clients/orders/access, XLSX, isolation and existing roots.")
    print(
        "Synthetic browser superadmin URL: http://localhost:5175/projects/shirin/products#tgWebAppData="
        + urlencode({"d": init_data(101)})[2:]
    )


asyncio.run(main())
