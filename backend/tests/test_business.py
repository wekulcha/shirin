import asyncio
import io
import secrets
import time
from decimal import Decimal
from xml.etree import ElementTree as ET
from zipfile import ZIP_DEFLATED, ZipFile

import pytest
from app.config import get_settings
from app.database import async_session
from app.models import ImportLog, Order, Outbox, Product, WebhookUpdate
from app.models.business import now
from app.schemas import ProductInput
from app.services.excel import COLUMNS, MAIN, build_workbook, worksheet
from app.services.notifications import chunks, notification_text, process_outbox_once
from app.services.telegram_auth import verify_telegram_init_data
from conftest import CUSTOMER, PRODUCT, add_product, init_data, place_order
from PIL import Image
from sqlalchemy import func, select


def workbook_with(rows):
    original = build_workbook([], True)
    out = io.BytesIO()
    with ZipFile(io.BytesIO(original)) as source, ZipFile(out, "w", ZIP_DEFLATED) as target:
        for info in source.infolist():
            content = (
                worksheet([COLUMNS, *[[row.get(key) for key in COLUMNS] for row in rows]], [20] * 16, True)
                if info.filename == "xl/worksheets/sheet1.xml"
                else source.read(info.filename)
            )
            target.writestr(info.filename, content)
    return out.getvalue()


async def preview(client, headers, content, uid=101):
    return await client.post("/shirin/api/catalog/preview", files={"file": ("catalog.xlsx", content)}, headers=headers[uid])


async def apply(client, headers, preview_id, uid=101):
    return await client.post(f"/shirin/api/catalog/previews/{preview_id}/apply", headers=headers[uid])


def test_sale_formats_and_disabled_fields():
    assert (
        ProductInput(**{**PRODUCT, "sell_by_package": False, "units_per_package": -1, "package_price_uzs": "bad"}).units_per_package is None
    )
    assert ProductInput(**{**PRODUCT, "sell_by_unit": False, "unit_price_uzs": "bad"}).unit_price_uzs is None
    for fields in (
        {"sell_by_unit": False, "sell_by_package": False},
        {"units_per_package": 0},
        {"package_price_uzs": "-1"},
        {"unit_price_uzs": "0.001"},
    ):
        with pytest.raises(ValueError):
            ProductInput(**{**PRODUCT, **fields})


def test_telegram_hmac_age_and_plus_decoding():
    data = init_data(202, extra={"query_id": "a+b c", "signature": "new-signature-field"})
    assert verify_telegram_init_data(data, get_settings().user_bot_token)["id"] == 202
    assert verify_telegram_init_data(init_data(202, age=3601), get_settings().user_bot_token) is None
    assert verify_telegram_init_data(data, "other-project-token") is None
    assert verify_telegram_init_data(data + "&auth_date=1", get_settings().user_bot_token) is None


async def test_order_snapshot_exact_price_and_idempotency(client, headers):
    product = await add_product(client, headers)
    order, payload = await place_order(client, headers, product)
    assert order["total_uzs"] == "306000.95"
    assert sum(line["base_units"] for line in order["lines"]) == 27
    assert order["status"] == "ACCEPTED" and order["payment_status"] == "UNPAID"
    repeat = await client.post("/shirin/api/orders", json=payload, headers=headers[202])
    assert repeat.json()["id"] == order["id"]
    await client.put(
        "/shirin/api/products/" + str(product["id"]),
        json={**PRODUCT, "name_ru": "Изменено", "package_price_uzs": "150000", "version": product["version"]},
        headers=headers[101],
    )
    old = (await client.get("/shirin/api/orders/" + str(order["id"]), headers=headers[202])).json()
    assert old["lines"][0]["name_ru"] == PRODUCT["name_ru"]
    assert old["total_uzs"] == "306000.95"
    async with async_session() as db:
        assert await db.scalar(select(func.count(Order.id))) == 1
        assert await db.scalar(select(func.count(Outbox.id))) == 1


async def test_concurrent_checkout_requests_one_order(client, headers):
    if not get_settings().database_url.startswith("postgresql"):
        pytest.skip("Row concurrency is verified against isolated PostgreSQL")
    product = await add_product(client, headers)
    data = {"lines": [{"product_id": product["id"], "sale_format": "unit", "quantity": 1}], "customer": CUSTOMER}
    quote = (await client.post("/shirin/api/orders/quote", json=data, headers=headers[202])).json()
    payload = {**data, "quote_token": quote["quote_token"], "attempt_key": secrets.token_hex(16)}
    responses = await asyncio.gather(*[client.post("/shirin/api/orders", json=payload, headers=headers[202]) for _ in range(2)])
    assert all(r.status_code == 201 for r in responses), [r.text for r in responses]
    assert len({r.json()["id"] for r in responses}) == 1


async def test_price_change_requires_new_confirmation(client, headers):
    product = await add_product(client, headers)
    data = {"lines": [{"product_id": product["id"], "sale_format": "unit", "quantity": 1}], "customer": CUSTOMER}
    quote = (await client.post("/shirin/api/orders/quote", json=data, headers=headers[202])).json()
    await client.put(
        "/shirin/api/products/" + str(product["id"]),
        json={**PRODUCT, "unit_price_uzs": "15000", "version": product["version"]},
        headers=headers[101],
    )
    result = await client.post(
        "/shirin/api/orders", json={**data, "quote_token": quote["quote_token"], "attempt_key": secrets.token_hex(16)}, headers=headers[202]
    )
    assert result.status_code == 409 and result.json()["detail"] == "conditions_changed"


@pytest.mark.parametrize("paid_first", [False, True])
async def test_delivery_and_payment_completion(client, headers, paid_first):
    product = await add_product(client, headers)
    order, _ = await place_order(client, headers, product)
    path = "/shirin/api/orders/" + str(order["id"])
    assert (await client.patch(path, json={"payment_status": "PAID"}, headers=headers[202])).status_code == 403
    assert (await client.patch(path, json={"status": "DELIVERED"}, headers=headers[303])).status_code == 409
    if paid_first:
        assert (await client.patch(path, json={"payment_status": "PAID"}, headers=headers[303])).json()["status"] == "ACCEPTED"
    await client.patch(path, json={"status": "READY"}, headers=headers[303])
    delivered = (await client.patch(path, json={"status": "DELIVERED"}, headers=headers[303])).json()
    assert delivered["status"] == ("COMPLETED" if paid_first else "DELIVERED")
    if not paid_first:
        assert (await client.patch(path, json={"payment_status": "PAID"}, headers=headers[303])).json()["status"] == "COMPLETED"
    before = (await client.get(path, headers=headers[303])).json()
    await client.patch(path, json={"payment_status": "PAID"}, headers=headers[303])
    after = (await client.get(path, headers=headers[303])).json()
    assert len(before["events"]) == len(after["events"]) == 4
    assert len(before["notifications"]) == len(after["notifications"]) == 4


async def test_permissions_customers_and_snapshot(client, headers):
    product = await add_product(client, headers)
    assert (await client.post("/shirin/api/products", json=PRODUCT, headers=headers[202])).status_code == 403
    created = await client.post("/shirin/api/customers", json={**CUSTOMER, "latitude": 41.311, "longitude": 69.279}, headers=headers[404])
    assert created.status_code == 201
    customer = created.json()
    assert "69.279%2C41.311" in customer["map_url"]
    assert (await client.get("/shirin/api/customers", headers=headers[202])).json() == []
    assert len((await client.get("/shirin/api/customers", headers=headers[303])).json()) == 1
    custom = {**CUSTOMER, "code": customer["code"], "address": "Адрес конкретной доставки 2"}
    order, _ = await place_order(client, headers, product, uid=303, customer_id=customer["id"], customer=custom)
    await client.put(
        "/shirin/api/customers/" + str(customer["id"]),
        json={**CUSTOMER, "name": "Новое имя", "code": customer["code"], "version": customer["version"]},
        headers=headers[404],
    )
    detail = (await client.get("/shirin/api/orders/" + str(order["id"]), headers=headers[303])).json()
    assert detail["customer_snapshot"]["name"] == CUSTOMER["name"]
    assert detail["customer_snapshot"]["address"] == custom["address"]
    assert (await client.get("/shirin/api/orders/" + str(order["id"]), headers=headers[505])).status_code == 403
    _, payload = await place_order(client, headers, product)
    denied = await client.post(
        "/shirin/api/orders/quote",
        json={k: v for k, v in {**payload, "save_customer": True}.items() if k not in ("quote_token", "attempt_key")},
        headers=headers[202],
    )
    assert denied.status_code == 403


async def test_excel_round_trip_text_sku_and_photo(client, headers):
    product = await add_product(client, headers, name_ru="=1+2")
    photo = io.BytesIO()
    Image.new("RGB", (30, 30), "green").save(photo, "PNG")
    result = await client.post(
        f"/shirin/api/products/{product['id']}/photo", files={"file": ("image.png", photo.getvalue())}, headers=headers[101]
    )
    assert result.status_code == 200
    exported = await client.get("/shirin/api/catalog/export", headers=headers[101])
    with ZipFile(io.BytesIO(exported.content)) as z:
        xml = ET.fromstring(z.read("xl/worksheets/sheet1.xml"))
        assert xml.find(f".//{{{MAIN}}}f") is None
    response = await preview(client, headers, exported.content)
    assert response.status_code == 200, response.text
    p = response.json()
    assert p["payload"]["counts"]["unchanged"] == 1 and not p["payload"]["errors"]
    assert (await apply(client, headers, p["id"])).status_code == 200
    products = (await client.get("/shirin/api/products", headers=headers[202])).json()
    assert products[0]["sku"] == "00001" and products[0]["photo_reference"] == result.json()["photo_reference"]
    assert (await apply(client, headers, p["id"])).status_code == 200
    async with async_session() as db:
        assert await db.scalar(select(func.count(ImportLog.id))) == 1


async def test_excel_blank_zero_false_clear_new_and_archive(client, headers):
    product = await add_product(client, headers)
    rows = [
        {"sku": product["sku"], "unit_price_uzs": Decimal("0"), "description_ru": "__CLEAR__", "sell_by_package": False},
        {**PRODUCT, "sku": "00002", "action": "upsert"},
    ]
    result = await preview(client, headers, workbook_with(rows))
    assert result.status_code == 200, result.text
    p = result.json()
    assert not p["payload"]["errors"], p
    assert (await apply(client, headers, p["id"])).status_code == 200
    async with async_session() as db:
        current = await db.get(Product, product["id"])
        assert current.unit_price_uzs == 0 and not current.sell_by_package and current.description_ru is None
        assert current.name_ru == PRODUCT["name_ru"]
    p = (await preview(client, headers, workbook_with([{"sku": "00001", "action": "archive"}]))).json()
    await apply(client, headers, p["id"])
    assert [p["sku"] for p in (await client.get("/shirin/api/products", headers=headers[202])).json()] == ["00002"]


async def test_excel_errors_permissions_and_atomic_conflict(client, headers):
    product = await add_product(client, headers)
    content = workbook_with([{"sku": "00001", "unit_price_uzs": -1}, {"sku": "00001"}])
    assert (await preview(client, headers, content, 202)).status_code == 403
    p = (await preview(client, headers, content)).json()
    assert p["payload"]["errors"]
    assert (await apply(client, headers, p["id"])).status_code == 422
    content = workbook_with([{"sku": "00001", "unit_price_uzs": Decimal("50")}, {**PRODUCT, "sku": "new"}])
    p = (await preview(client, headers, content)).json()
    assert (await apply(client, headers, p["id"], 404)).status_code == 404
    await client.put(
        f"/shirin/api/products/{product['id']}",
        json={**PRODUCT, "unit_price_uzs": "99", "version": product["version"]},
        headers=headers[101],
    )
    assert (await apply(client, headers, p["id"])).status_code == 409
    async with async_session() as db:
        assert await db.scalar(select(func.count(Product.id))) == 1
        assert (await db.get(Product, product["id"])).unit_price_uzs == 99


async def test_excel_reject_formula_macro_numeric_sku(client, headers):
    content = workbook_with([{**PRODUCT, "sku": "001"}])
    for malicious in ("formula", "macro", "external"):
        out = io.BytesIO()
        with ZipFile(io.BytesIO(content)) as src, ZipFile(out, "w", ZIP_DEFLATED) as dst:
            for info in src.infolist():
                data = src.read(info.filename)
                if malicious == "formula" and info.filename == "xl/worksheets/sheet1.xml":
                    root = ET.fromstring(data)
                    cell = root.find(f'.//{{{MAIN}}}row[@r="2"]/{{{MAIN}}}c[@r="M2"]')
                    ET.SubElement(cell, f"{{{MAIN}}}f").text = "1+1"
                    data = ET.tostring(root)
                dst.writestr(info.filename, data)
            if malicious == "macro":
                dst.writestr("xl/vbaProject.bin", b"not-a-macro")
            if malicious == "external":
                dst.writestr("xl/externalLinks/externalLink1.xml", b"<link/>")
        result = await preview(client, headers, out.getvalue())
        if malicious == "formula":
            assert any(e["code"] == "formula_not_allowed" for e in result.json()["payload"]["errors"])
        else:
            assert result.status_code == 422
    numeric = (await preview(client, headers, workbook_with([{**PRODUCT, "sku": 123}]))).json()
    assert any(e["code"] == "sku_must_be_text" for e in numeric["payload"]["errors"])


class FakeTransport:
    def __init__(self, failure=False):
        self.failure = failure
        self.messages = []

    async def send(self, payload, part, index):
        if self.failure:
            raise TimeoutError("secret must not be persisted")
        self.messages.append(part)
        return len(self.messages)


async def test_outbox_survives_failure_and_restart(client, headers):
    product = await add_product(client, headers)
    order, _ = await place_order(client, headers, product)
    assert await process_outbox_once(FakeTransport(True))
    async with async_session() as db:
        entry = await db.scalar(select(Outbox))
        assert entry.state == "PENDING" and entry.last_error == "TimeoutError"
        assert await db.get(Order, order["id"])
        entry.next_attempt_at = now()
        await db.commit()
    transport = FakeTransport()
    assert await process_outbox_once(transport)
    async with async_session() as db:
        entry = await db.scalar(select(Outbox))
        assert entry.state == "SENT" and entry.message_ids
    assert not await process_outbox_once(transport)
    text = notification_text({"kind": "created", "order": order}, "uz")
    assert "UZS" in text and "Do‘kon" in text and "quti" in text
    assert all(len(part.encode("utf-16-le")) // 2 <= 3500 for part in chunks("😀" * 6000))


async def test_media_validation_and_protected_store_photo(client, headers):
    rejected = await client.post("/shirin/api/media/upload?kind=store", files={"file": ("fake.jpg", b"not image")}, headers=headers[202])
    assert rejected.status_code == 422
    photo = io.BytesIO()
    Image.new("RGB", (30, 30)).save(photo, "PNG")
    result = await client.post("/shirin/api/media/upload?kind=store", files={"file": ("store.png", photo.getvalue())}, headers=headers[202])
    path = result.json()["path"]
    assert (await client.get(path)).status_code == 401
    assert (await client.get(path, headers=headers[202])).status_code == 200
    assert (await client.get(path, headers=headers[505])).status_code == 403


async def test_removed_integration_cannot_authenticate(client):
    headers = {"X-Shirin-Actor": "101", "X-Shirin-Timestamp": str(int(time.time())), "X-Shirin-Nonce": secrets.token_hex(20), "X-Shirin-Signature": "retired-signature"}
    for path in ("/shirin/api/settings", "/shirin/api/superadmin/me", "/shirin/api/access"):
        result = await client.get(path, headers=headers)
        assert result.status_code == 401 and result.json()["detail"] == "login_required"
    assert verify_telegram_init_data(init_data(202), "market-bot-token") is None


async def test_webhook_auth_redelivery_and_json_404(client):
    update = {
        "update_id": 123,
        "message": {
            "message_id": 1,
            "date": 1,
            "chat": {"id": 101, "type": "private"},
            "text": "/start",
            "from": {"id": 101, "is_bot": False, "first_name": "Test"},
        },
    }
    path = "/shirin/webhooks/telegram/"
    assert (await client.post(path, json=update)).status_code == 403
    for _ in range(2):
        assert (
            await client.post(path, json=update, headers={"X-Telegram-Bot-Api-Secret-Token": get_settings().webhook_secret})
        ).status_code == 200
    async with async_session() as db:
        assert await db.scalar(select(func.count(WebhookUpdate.id))) == 1
    # Telegram update IDs can coincide between bots; deduplicate within each role.
    for role in ("admin", "superadmin"):
        for _ in range(2):
            result = await client.post(
                f"/shirin/webhooks/telegram/{role}/", json=update,
                headers={"X-Telegram-Bot-Api-Secret-Token": get_settings().webhook_secret},
            )
            assert result.status_code == 200
    async with async_session() as db:
        assert await db.scalar(select(func.count(WebhookUpdate.id))) == 3
        assert {row.bot_role for row in (await db.scalars(select(WebhookUpdate))).all()} == {"user", "admin", "superadmin"}
    result = await client.get("/shirin/api/missing")
    assert result.status_code == 404 and result.headers["content-type"].startswith("application/json")
