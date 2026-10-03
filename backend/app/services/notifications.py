import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from pathlib import Path
from zoneinfo import ZoneInfo

from aiogram import Bot
from aiogram.types import FSInputFile, InlineKeyboardButton, InlineKeyboardMarkup
from sqlalchemy import or_, select, update

from app.config import get_settings
from app.database import async_session
from app.i18n import translate
from app.models import Media, Outbox
from app.models.business import now


def money(value) -> str:
    return f"{Decimal(value):,.2f}".replace(",", " ").rstrip("0").rstrip(".") + " UZS"


def notification_text(payload: dict, lang: str) -> str:
    def t(key):
        return translate(key, lang)

    o = payload["order"]
    c = o["customer_snapshot"]
    text = [
        f"{t('new_order') if payload['kind'] == 'created' else t('update_order')} {o['number']}",
        "",
        f"{t('agent')}: {o['author_snapshot']['name']} ({o['author_id']})",
    ]
    for key, label in [("name", "store"), ("code", "code"), ("contact_name", "contact"), ("phone", "phone"), ("address", "address")]:
        if c.get(key):
            text.append(f"{t(label)}: {c[key]}")
    if c.get("latitude") is not None:
        text.append(f"{t('coordinates')}: {c['latitude']}, {c['longitude']}")
    if c.get("map_url"):
        text.append(f"{t('map')}: {c['map_url']}")
    text += ["", t("items") + ":"]
    for index, line in enumerate(o["lines"], 1):
        size = f" × {line['units_per_package']} {t('unit')}" if line["sale_format"] == "package" else ""
        text += [
            f"{index}. {line['name_' + lang]} ({line['sku']}) — {line['quantity']} {t(line['sale_format'])}{size}",
            f"{money(line['price_uzs'])} × {line['quantity']} = {money(line['amount_uzs'])}",
        ]
    text += ["", f"{t('total')}: {money(o['total_uzs'])}", f"{t('order')}: {t(o['status'])}", f"{t('payment')}: {t(o['payment_status'])}"]
    if c.get("comment"):
        text.append(f"{t('comment')}: {c['comment']}")
    date = datetime.fromisoformat(o["created_at"].replace("Z", "+00:00")).astimezone(ZoneInfo(get_settings().timezone))
    text.append(f"{t('date')}: {date:%d.%m.%Y %H:%M}")
    return "\n".join(text)


def chunks(text: str, limit: int = 3500) -> list[str]:
    parts, current, units = [], "", 0
    for char in text:
        size = len(char.encode("utf-16-le")) // 2
        if units + size > limit:
            parts.append(current)
            current, units = "", 0
        current += char
        units += size
    if current:
        parts.append(current)
    return parts


class TelegramTransport:
    def __init__(self):
        self.bot = Bot(get_settings().user_bot_token)

    async def send(self, payload: dict, part: str, index: int) -> int:
        settings = get_settings()
        o = payload["order"]
        lang = settings.group_language
        buttons = [[InlineKeyboardButton(text=translate("open", lang), url=settings.admin_app_url + "orders/" + str(o["id"]))]]
        if o["customer_snapshot"].get("map_url"):
            buttons.append([InlineKeyboardButton(text=translate("map", lang), url=o["customer_snapshot"]["map_url"])])
        if o["status"] == "ACCEPTED":
            buttons.append([InlineKeyboardButton(text=translate("READY", lang), callback_data=f"order:{o['id']}:READY")])
        elif o["status"] == "READY":
            buttons.append([InlineKeyboardButton(text=translate("DELIVERED", lang), callback_data=f"order:{o['id']}:DELIVERED")])
        if o["payment_status"] != "PAID":
            buttons.append([InlineKeyboardButton(text=translate("PAID", lang), callback_data=f"order:{o['id']}:PAID")])
        kwargs = {"chat_id": settings.work_group_id, "message_thread_id": settings.work_group_topic_id or None}
        if index == 0 and payload.get("photo_path"):
            result = await self.bot.send_photo(
                **kwargs,
                photo=FSInputFile(payload["photo_path"]),
                caption=o["number"],
                reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons),
            )
        else:
            result = await self.bot.send_message(
                **kwargs, text=part, reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons) if index == 0 else None, parse_mode=None
            )
        return result.message_id

    async def close(self):
        await self.bot.session.close()


async def process_outbox_once(transport=None) -> bool:
    settings = get_settings()
    if transport is None and (not settings.user_bot_token or not settings.work_group_id):
        return False
    async with async_session() as db:
        due = or_(Outbox.state == "PENDING", (Outbox.state == "SENDING") & (Outbox.lease_until < now()))
        entry = await db.scalar(
            select(Outbox).where(due, Outbox.next_attempt_at <= now()).order_by(Outbox.id).with_for_update(skip_locked=True).limit(1)
        )
        if not entry:
            return False
        claimed = await db.execute(
            update(Outbox)
            .where(Outbox.id == entry.id, due)
            .values(state="SENDING", lease_until=now() + timedelta(minutes=5), attempts=Outbox.attempts + 1)
        )
        if claimed.rowcount != 1:
            await db.rollback()
            return False
        await db.commit()
        entry_id = entry.id
    owned = transport is None
    transport = transport or TelegramTransport()
    try:
        async with async_session() as db:
            entry = await db.get(Outbox, entry_id)
            payload = dict(entry.payload)
            photo = payload["order"]["customer_snapshot"].get("photo_reference")
            photo_path = None
            if photo and payload["kind"] == "created":
                media = await db.get(Media, photo.rsplit("/", 1)[-1])
                if media and not media.storage_path.startswith("https://") and Path(media.storage_path).is_file():
                    photo_path = media.storage_path
            parts = chunks(notification_text(payload, settings.group_language))
            if photo_path:
                payload["photo_path"] = photo_path
                parts.insert(0, "")
            for index in range(len(entry.message_ids), len(parts)):
                mid = await transport.send(payload, parts[index], index)
                entry.message_ids = [*entry.message_ids, mid]
                entry.lease_until = now() + timedelta(minutes=5)
                await db.commit()
            entry.state = "SENT"
            entry.lease_until = None
            entry.last_error = None
            await db.commit()
    except Exception as exc:
        async with async_session() as db:
            entry = await db.get(Outbox, entry_id)
            entry.state = "PENDING"
            entry.lease_until = None
            entry.last_error = type(exc).__name__  # Never store tokens or customer data from exception URLs.
            delay = max(min(2 ** min(entry.attempts, 10), 600), int(getattr(exc, "retry_after", 0)))
            entry.next_attempt_at = now() + timedelta(seconds=delay)
            await db.commit()
    finally:
        if owned:
            await transport.close()
    return True


async def run_worker():
    while True:
        if not await process_outbox_once():
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(run_worker())
