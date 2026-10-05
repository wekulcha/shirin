"""Synthetic local sandbox only. No real Telegram calls or production data."""

import asyncio
import hashlib
import hmac
import json
import secrets
import subprocess
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

ROOT = Path(__file__).resolve().parents[1]
env_file = ROOT / ".env"
if not env_file.exists():
    env_file.write_text(
        "\n".join(
            [
                "SHIRIN_ENVIRONMENT=development",
                f"SHIRIN_DATABASE_URL=sqlite+aiosqlite:///{ROOT / 'demo.db'}",
                "SHIRIN_AUTH_COOKIE_SECURE=false",
                "SHIRIN_AUTH_ACCESS_SECRET=" + secrets.token_urlsafe(40),
                "SHIRIN_USER_BOT_TOKEN=123456:" + secrets.token_urlsafe(35),
                "SHIRIN_ADMIN_BOT_TOKEN=234567:" + secrets.token_urlsafe(35),
                "SHIRIN_SUPERADMIN_BOT_TOKEN=345678:" + secrets.token_urlsafe(35),
                "SHIRIN_SUPERADMIN_ALLOWED_IDS=101",
                "SHIRIN_WORK_GROUP_ID=0",
                "SHIRIN_UPLOADS_DIR=" + str(ROOT / "uploads"),
                "SHIRIN_INIT_DATA_TTL_SECONDS=600",
                "SHIRIN_CORS_ALLOWED_ORIGINS=http://localhost:5183,http://localhost:5184,http://localhost:5185,http://localhost:8093,http://localhost:8094,http://localhost:8095",
            ]
        )
        + "\n"
    )
    env_file.chmod(0o600)
sys.path.insert(0, str(ROOT / "backend"))
from app.config import get_settings  # noqa: E402

settings = get_settings()
expected_url = f"sqlite+aiosqlite:///{ROOT / 'demo.db'}"
if settings.environment != "development" or settings.database_url != expected_url or settings.work_group_id:
    raise SystemExit("Refusing demo seed outside the isolated local development database with no work group.")

# Upgrade an existing isolated demo to three synthetic bot identities.
missing_tokens = [role for role in ("admin", "superadmin") if not settings.bot_token_for(role)]
if missing_tokens:
    with env_file.open("a") as demo_env:
        for index, role in enumerate(missing_tokens, 2):
            demo_env.write(f"SHIRIN_{role.upper()}_BOT_TOKEN={index}23456:" + secrets.token_urlsafe(35) + "\n")
    get_settings.cache_clear()
    settings = get_settings()


async def seed():
    from app.database import async_session, engine
    from app.models import Customer, Product, Staff
    from app.services.session_auth import ensure_customer
    from sqlalchemy import select

    subprocess.run([str(ROOT / ".venv/bin/alembic"), "upgrade", "head"], cwd=ROOT / "backend", check=True)
    async with async_session() as db:
        for uid, name in [(101, "Demo admin"), (202, "Demo agent"), (303, "Demo user")]:
            await ensure_customer(db, uid, name)
        if not await db.scalar(select(Staff.id).where(Staff.user_id == 202)):
            db.add(Staff(user_id=202, permission="CAN_LOOK_ORDERS"))
        if not await db.scalar(select(Product.id)):
            db.add_all(
                [
                    Product(
                        sku="DEMO-001",
                        brand="Ширин",
                        category="Соки / Sharbatlar",
                        name_ru="Яблочный сок",
                        name_uz="Olma sharbati",
                        description_ru="Демонстрационный товар · 1 л",
                        description_uz="Namoyish mahsuloti · 1 l",
                        volume_ml=1000,
                        sell_by_unit=True,
                        sell_by_package=True,
                        units_per_package=12,
                        unit_price_uzs="12000",
                        package_price_uzs="135000",
                    ),
                    Product(
                        sku="DEMO-002",
                        brand="Сады Востока",
                        category="Нектары / Nektarlar",
                        name_ru="Абрикосовый нектар",
                        name_uz="O‘rik nektari",
                        description_ru="Демонстрационный товар · только ящиками",
                        description_uz="Namoyish mahsuloti · faqat qutilar",
                        volume_ml=1000,
                        sell_by_unit=False,
                        sell_by_package=True,
                        units_per_package=6,
                        package_price_uzs="72000",
                    ),
                    Product(
                        sku="DEMO-003",
                        brand="Ширин",
                        category="Соки / Sharbatlar",
                        name_ru="Гранатовый сок",
                        name_uz="Anor sharbati",
                        description_ru="Демонстрационный товар · только бутылками",
                        description_uz="Namoyish mahsuloti · faqat shishalar",
                        volume_ml=250,
                        sell_by_unit=True,
                        sell_by_package=False,
                        unit_price_uzs="8000",
                    ),
                ]
            )
        if not await db.scalar(select(Customer.id)):
            db.add(
                Customer(
                    code="DEMO-STORE",
                    name="Демо магазин",
                    contact_name="Демо контакт",
                    phone="+998900000001",
                    address="Ташкент · демонстрационный адрес",
                    created_by=101,
                    latitude=41.311,
                    longitude=69.279,
                    map_url="https://yandex.uz/maps/?pt=69.279,41.311&z=17&l=map",
                )
            )
        await db.commit()
    await engine.dispose()


def login_data(uid, role):
    values = {"auth_date": str(int(time.time())), "user": json.dumps({"id": uid, "first_name": "Demo"}, separators=(",", ":"))}
    key = hmac.new(b"WebAppData", settings.bot_token_for(role).encode(), hashlib.sha256).digest()
    values["hash"] = hmac.new(key, "\n".join(f"{k}={v}" for k, v in sorted(values.items())).encode(), hashlib.sha256).hexdigest()
    return urlencode(values)


if "--links-only" not in sys.argv:
    asyncio.run(seed())
ports = (8093, 8094, 8095) if "--built" in sys.argv else (5183, 5184, 5185)
links = [("Mini App", ports[0], 202, "", "user"), ("Admin", ports[1], 202, "orders", "admin"), ("Superadmin", ports[2], 101, "superadmin/", "superadmin")]
for label, port, uid, page, role in links:
    if "--superadmin" in sys.argv and label != "Superadmin":
        continue
    print(f"{label}: http://localhost:{port}/shirin/{page}#tgWebAppData={quote(login_data(uid, role), safe='')}")
print("Synthetic demo only. Signed login links expire after 10 minutes. Work group notifications are disabled.")
