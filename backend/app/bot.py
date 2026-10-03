"""One aiogram bot; durable dialogs and shared backend business services."""

import asyncio
import io
import logging
import secrets
from datetime import timedelta

from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command
from aiogram.types import BufferedInputFile, CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message, Update, WebAppInfo
from fastapi import HTTPException
from sqlalchemy import select

from app.config import get_settings
from app.database import async_session
from app.i18n import translate
from app.models import BotState, Media, Product, User, WebhookUpdate
from app.models.business import Permission, now
from app.schemas import ProductInput, Transition
from app.services.access import actor_for_user
from app.services.catalog import save_product, serialize
from app.services.excel import apply_import, build_workbook, preview_import
from app.services.media import attach_product_photo, checked_image, upload_media
from app.services.notifications import chunks
from app.services.orders import transition
from app.services.session_auth import ensure_customer

router = Router()
logger = logging.getLogger(__name__)


def language(user) -> str:
    return "uz" if user.language_code == "uz" else "ru"


async def lang_for(db, telegram_user) -> str:
    user = await db.get(User, telegram_user.id)
    return user.language if user else language(telegram_user)


def keyboard(rows) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=rows)


def cancel_button(lang: str):
    return InlineKeyboardButton(text=translate("cancel", lang), callback_data="cancel")


async def set_state(db, uid: int, kind: str, payload: dict):
    state = await db.get(BotState, uid)
    if not state:
        state = BotState(user_id=uid, kind=kind, payload=payload, expires_at=now() + timedelta(minutes=30))
        db.add(state)
    else:
        state.kind, state.payload, state.expires_at = kind, payload, now() + timedelta(minutes=30)
    await db.flush()
    return state


async def menu(message: Message, telegram_user=None):
    settings = get_settings()
    telegram_user = telegram_user or message.from_user
    async with async_session() as db:
        user = await ensure_customer(db, telegram_user.id, telegram_user.username or telegram_user.first_name)
        actor = await actor_for_user(db, user)
        lang = user.language

        def t(key):
            return translate(key, lang)

        rows = [[InlineKeyboardButton(text=t("catalog"), web_app=WebAppInfo(url=settings.mini_app_url))]]
        if actor.superadmin:
            rows.append([InlineKeyboardButton(text=t("superadmin"), web_app=WebAppInfo(url=settings.superadmin_app_url))])
        if actor.permissions or actor.superadmin:
            rows.append([InlineKeyboardButton(text=t("admin"), web_app=WebAppInfo(url=settings.admin_app_url))])
        if actor.has(Permission.CAN_EDIT_MENU):
            for command, text in [
                ("export_meals", "export"),
                ("update_meals", "update"),
                ("add_meal", "add"),
                ("remove_meal", "archive"),
                ("set_photo", "photo"),
            ]:
                rows.append([InlineKeyboardButton(text=t(text), callback_data="cmd:" + command)])
        rows.append(
            [InlineKeyboardButton(text="Русский", callback_data="lang:ru"), InlineKeyboardButton(text="O‘zbekcha", callback_data="lang:uz")]
        )
        await db.commit()
    await message.answer(t("welcome"), reply_markup=keyboard(rows))


@router.message(Command("start", "help"))
async def start(message: Message):
    if message.chat.type != "private":
        return
    await menu(message)


async def command_action(message: Message, telegram_user, command: str):
    if message.chat.type != "private":
        return
    async with async_session() as db:
        user = await ensure_customer(db, telegram_user.id, telegram_user.username or telegram_user.first_name)
        actor = await actor_for_user(db, user)
        lang = user.language
        actor.require(Permission.CAN_EDIT_MENU)

        def t(key):
            return translate(key, lang)

        if command in ("export_meals", "update_meals", "add_meal"):
            products = (await db.scalars(select(Product).order_by(Product.sku))).all()
            workbook = await asyncio.to_thread(build_workbook, products, command == "add_meal")
            await message.answer_document(BufferedInputFile(workbook, filename="shirin-catalog.xlsx"))
            if command != "export_meals":
                await set_state(db, user.id, "excel", {})
                await message.answer(t("upload_excel"), reply_markup=keyboard([[cancel_button(lang)]]))
        else:
            token = secrets.token_hex(8)
            kind = "photo_select" if command == "set_photo" else "archive_select"
            await set_state(db, user.id, kind, {"token": token})
            await product_choices(db, message, lang, kind, token)
        await db.commit()


async def product_choices(db, message: Message, lang: str, kind: str, token: str, q: str = ""):
    query = select(Product)
    if q:
        from sqlalchemy import or_

        query = query.where(or_(Product.sku.ilike(f"%{q}%"), Product.name_ru.ilike(f"%{q}%"), Product.name_uz.ilike(f"%{q}%")))
    products = (await db.scalars(query.order_by(Product.id).limit(20))).all()
    rows = [
        [InlineKeyboardButton(text=f"{p.sku} · {getattr(p, 'name_' + lang)}"[:60], callback_data=f"select:{token}:{p.id}")]
        for p in products
    ]
    rows.append([cancel_button(lang)])
    await message.answer(translate("choose", lang) + " · SKU / 🔎", reply_markup=keyboard(rows))


@router.message(Command("export_meals", "update_meals", "add_meal", "remove_meal", "set_photo"))
async def admin_command(message: Message):
    try:
        await command_action(message, message.from_user, message.text.split()[0].split("@")[0][1:])
    except HTTPException as exc:
        async with async_session() as db:
            lang = await lang_for(db, message.from_user)
        await message.answer(translate("access_denied" if exc.status_code == 403 else "error", lang))


@router.callback_query(F.data.startswith("cmd:"))
async def button_command(callback: CallbackQuery):
    try:
        await command_action(callback.message, callback.from_user, callback.data.split(":", 1)[1])
        await callback.answer()
    except HTTPException:
        async with async_session() as db:
            lang = await lang_for(db, callback.from_user)
        await callback.answer(translate("access_denied", lang), show_alert=True)


@router.callback_query(F.data.startswith("lang:"))
async def change_language(callback: CallbackQuery):
    async with async_session() as db:
        user = await ensure_customer(db, callback.from_user.id, callback.from_user.username or callback.from_user.first_name)
        lang = callback.data.split(":")[1]
        if lang in ("ru", "uz"):
            user.language = lang
            await db.commit()
    await callback.answer(translate("done", lang))
    await menu(callback.message, callback.from_user)


@router.message(Command("cancel"))
async def cancel_command(message: Message):
    async with async_session() as db:
        await cancel_dialog(db, message.from_user.id)
        lang = await lang_for(db, message.from_user)
        await db.commit()
    await message.answer(translate("cancel", lang))


async def cancel_dialog(db, user_id: int):
    state = await db.get(BotState, user_id)
    if state:
        if state.kind == "excel_confirm":
            from app.models import ImportPreview

            preview = await db.get(ImportPreview, state.payload["preview_id"])
            if preview and preview.actor_id == user_id and preview.state == "PENDING":
                preview.state = "CANCELLED"
        await db.delete(state)


@router.callback_query(F.data == "cancel")
async def cancel_callback(callback: CallbackQuery):
    async with async_session() as db:
        await cancel_dialog(db, callback.from_user.id)
        lang = await lang_for(db, callback.from_user)
        await db.commit()
    await callback.answer(translate("cancel", lang))
    await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.startswith("select:"))
async def select_product(callback: CallbackQuery):
    async with async_session() as db:
        user = await ensure_customer(db, callback.from_user.id, callback.from_user.username)
        actor = await actor_for_user(db, user)
        lang = user.language
        try:
            actor.require(Permission.CAN_EDIT_MENU)
            state = await db.get(BotState, user.id)
            _, token, pid = callback.data.split(":")
            if (
                not state
                or state.expires_at < now()
                or state.kind not in ("photo_select", "archive_select")
                or state.payload.get("token") != token
            ):
                raise HTTPException(409, "expired")
            product = await db.get(Product, int(pid))
            if not product:
                raise HTTPException(404, "expired")
            payload = {"product_id": product.id, "version": product.version, "token": token}
            if state.kind == "photo_select":
                await set_state(db, user.id, "photo_wait", payload)
                await callback.message.answer(
                    f"{product.sku} · {getattr(product, 'name_' + lang)}\n" + translate("upload_photo", lang),
                    reply_markup=keyboard([[cancel_button(lang)]]),
                )
            else:
                await set_state(db, user.id, "archive_confirm", payload)
                await callback.message.answer(
                    f"{product.sku} · {getattr(product, 'name_' + lang)}\n" + translate("archive_confirm", lang),
                    reply_markup=keyboard(
                        [[InlineKeyboardButton(text=translate("apply", lang), callback_data=f"confirm:{token}"), cancel_button(lang)]]
                    ),
                )
            await db.commit()
            await callback.answer()
        except HTTPException as exc:
            await callback.answer(translate("access_denied" if exc.status_code == 403 else "expired", lang), show_alert=True)


@router.message(F.document | F.photo)
async def uploaded_file(message: Message, bot: Bot):
    if message.chat.type != "private":
        return
    async with async_session() as db:
        user = await ensure_customer(db, message.from_user.id, message.from_user.username)
        actor = await actor_for_user(db, user)
        lang = user.language
        try:
            actor.require(Permission.CAN_EDIT_MENU)
            state = await db.get(BotState, user.id)
            if not state or state.expires_at < now() or state.kind not in ("excel", "photo_wait"):
                raise HTTPException(409, "expired")
            file = message.document or message.photo[-1]
            if file.file_size and file.file_size > get_settings().max_upload_bytes:
                raise HTTPException(413, "file_too_large")
            if state.kind == "excel" and (not message.document or not message.document.file_name.lower().endswith(".xlsx")):
                raise HTTPException(422, "invalid_workbook")
            downloaded = io.BytesIO()
            await bot.download(file, destination=downloaded)
            content = downloaded.getvalue()
            token = secrets.token_hex(8)
            if state.kind == "excel":
                preview = await preview_import(db, actor, content)
                await set_state(db, user.id, "excel_confirm", {"preview_id": preview.id, "token": token})
                # Full row/column diagnostics and before/after diff, not only counts.
                lines = [f"{translate(k, lang)}: {v}" for k, v in preview.payload["counts"].items()]
                for e in preview.payload["errors"]:
                    lines.append(f"{translate('row', lang)} {e['row']} · {e['column']}: {translate(e['code'], lang)}")
                for warning in preview.payload["warnings"]:
                    lines.append(f"{translate('row', lang)} {warning['row']} · {warning['column']}: {translate(warning['code'], lang)}")
                for c in preview.payload["changes"]:
                    if c["diff"]:
                        lines.append(c["sku"] + "\n" + "\n".join(f"{k}: {v['before']} → {v['after']}" for k, v in c["diff"].items()))
                buttons = [cancel_button(lang)]
                if not preview.payload["errors"]:
                    buttons.insert(0, InlineKeyboardButton(text=translate("apply", lang), callback_data="confirm:" + token))
                for part in chunks("\n".join(lines)):
                    await message.answer(part)
                await message.answer(
                    translate("use_app", lang),
                    reply_markup=keyboard(
                        [
                            buttons,
                            [
                                InlineKeyboardButton(
                                    text=translate("admin", lang),
                                    web_app=WebAppInfo(url=get_settings().admin_app_url + "import/" + preview.id),
                                )
                            ],
                        ]
                    ),
                )
            else:
                checked, _, _ = await asyncio.to_thread(checked_image, content)
                media = await upload_media(db, actor, checked, "product")
                product = await db.get(Product, state.payload["product_id"])
                if not product or product.version != state.payload["version"]:
                    raise HTTPException(409, "changed_since_preview")
                await set_state(db, user.id, "photo_confirm", {**state.payload, "media_id": media.id, "token": token})
                await message.answer_photo(
                    BufferedInputFile(checked, filename="preview.jpg"),
                    caption=f"{product.sku} · {getattr(product, 'name_' + lang)}\n" + translate("photo_confirm", lang),
                    reply_markup=keyboard(
                        [[InlineKeyboardButton(text=translate("apply", lang), callback_data="confirm:" + token), cancel_button(lang)]]
                    ),
                )
            await db.commit()
        except HTTPException as exc:
            await message.answer(
                translate("access_denied" if exc.status_code == 403 else "expired" if exc.detail == "expired" else "error", lang)
            )


@router.message(F.text)
async def search_product(message: Message):
    if message.chat.type != "private":
        return
    async with async_session() as db:
        user = await ensure_customer(db, message.from_user.id, message.from_user.username)
        state = await db.get(BotState, user.id)
        actor = await actor_for_user(db, user)
        if state and state.kind in ("photo_select", "archive_select") and state.expires_at > now() and actor.has(Permission.CAN_EDIT_MENU):
            await product_choices(db, message, user.language, state.kind, state.payload["token"], message.text[:100])


@router.callback_query(F.data.startswith("confirm:"))
async def confirm(callback: CallbackQuery):
    async with async_session() as db:
        user = await ensure_customer(db, callback.from_user.id, callback.from_user.username)
        actor = await actor_for_user(db, user)
        lang = user.language
        try:
            actor.require(Permission.CAN_EDIT_MENU)
            state = await db.scalar(select(BotState).where(BotState.user_id == user.id).with_for_update())
            if not state or state.expires_at < now() or state.payload.get("token") != callback.data.split(":")[1]:
                raise HTTPException(409, "expired")
            if state.kind == "excel_confirm":
                await apply_import(db, actor, state.payload["preview_id"])
            elif state.kind in ("photo_confirm", "archive_confirm"):
                product = await db.scalar(select(Product).where(Product.id == state.payload["product_id"]).with_for_update())
                if not product or product.version != state.payload["version"]:
                    raise HTTPException(409, "changed_since_preview")
                if state.kind == "photo_confirm":
                    media = await db.get(Media, state.payload["media_id"])
                    await attach_product_photo(db, actor, product, media)
                else:
                    values = {k: serialize(product)[k] for k in ProductInput.model_fields}
                    values["is_active"] = False
                    await save_product(db, actor, ProductInput.model_validate(values), product.id, product.version)
            else:
                raise HTTPException(409, "expired")
            await db.delete(state)
            await db.commit()
            await callback.answer(translate("done", lang))
            await callback.message.edit_reply_markup(reply_markup=None)
        except HTTPException as exc:
            key = "access_denied" if exc.status_code == 403 else exc.detail if isinstance(exc.detail, str) else "error"
            await callback.answer(translate(key, lang) if key in ("access_denied", "expired", "changed_since_preview", "preview_expired", "import_has_errors") else translate("error", lang), show_alert=True)


@router.callback_query(F.data.startswith("order:"))
async def order_button(callback: CallbackQuery):
    async with async_session() as db:
        user = await ensure_customer(db, callback.from_user.id, callback.from_user.username or callback.from_user.first_name)
        actor = await actor_for_user(db, user)
        lang = user.language
        try:
            _, oid, action = callback.data.split(":")
            result = await transition(
                db, actor, int(oid), Transition(payment_status="PAID") if action == "PAID" else Transition(status=action)
            )
            await db.commit()
            await callback.answer(f"{translate(result.status, lang)} · {translate(result.payment_status, lang)}", show_alert=True)
        except (HTTPException, ValueError):
            await callback.answer(translate("access_denied", lang), show_alert=True)


def dispatcher() -> Dispatcher:
    dp = Dispatcher()
    dp.include_router(router)
    return dp


async def run_bot():
    settings = get_settings()
    if not settings.user_bot_token:
        raise RuntimeError("SHIRIN_USER_BOT_TOKEN is required")
    bot = Bot(settings.user_bot_token)
    dp = dispatcher()
    try:
        if settings.bot_mode == "polling":
            # No implicit deleteWebhook/setWebhook: production lifecycle is operator-controlled.
            await dp.start_polling(bot)
        elif settings.bot_mode == "webhook":
            while True:
                async with async_session() as db:
                    entry = await db.scalar(
                        select(WebhookUpdate)
                        .where(WebhookUpdate.state == "PENDING", WebhookUpdate.next_attempt_at <= now())
                        .order_by(WebhookUpdate.id)
                        .limit(1)
                    )
                    if entry:
                        try:
                            await dp.feed_update(bot, Update.model_validate(entry.payload))
                            entry.state = "DONE"
                            entry.payload = {}  # Discard processed PII.
                        except Exception as exc:
                            entry.attempts += 1
                            entry.next_attempt_at = now() + timedelta(seconds=min(2 ** min(entry.attempts, 10), 600))
                            logger.warning("Webhook update processing failed: %s", type(exc).__name__)
                        await db.commit()
                if not entry:
                    await asyncio.sleep(2)
        else:
            raise RuntimeError("SHIRIN_BOT_MODE must be polling or webhook")
    finally:
        await bot.session.close()


if __name__ == "__main__":
    asyncio.run(run_bot())
